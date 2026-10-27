"""Supervised hidden worker; generated policy cells are never run on CPU tests."""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import zipfile

if __package__:
    from .entry_runtime import Budget, competition_games, finish_benchmark, wait_gateway
else:
    from entry_runtime import Budget, competition_games, finish_benchmark, wait_gateway


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify_tree(root, expected):
    root = Path(root).resolve()
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual != set(expected):
        raise ValueError('Source inventory drift')
    for name, digest in expected.items():
        path = root / name
        if not path.resolve().is_relative_to(root) or sha(path) != digest:
            raise ValueError('Source identity drift')


def prepare_source(package, private, source):
    manifest = json.loads((package / 'source-manifest.json').read_text())
    verify_tree(source, manifest['raw_files'])
    bundle = private / 'bundle'
    shutil.copytree(source, bundle)
    patch = package / 'harness-changes.patch'
    if sha(patch) != manifest['patch_sha256']:
        raise ValueError('Entry patch identity drift')
    subprocess.run(['git', '-c', 'core.autocrlf=true', 'apply', '--include=ARC3-Inference/*', str(patch)],
                   cwd=bundle / 'src', check=True, timeout=30,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    verify_tree(bundle, manifest['effective_files'])
    from entry_diagnostics import adapt_sources
    report = adapt_sources(bundle / 'src')
    expected_adaptation = json.loads((package / 'diagnostics-manifest.json').read_text())
    if report != expected_adaptation:
        raise ValueError('Diagnostics-only adaptation identity drift')
    # Every import/unpickle occurs only after raw/effective identity verification.
    return bundle


def verify_inputs(pins):
    for name, digest in pins['hashed_files'].items():
        if sha(Path('/kaggle/input') / name) != digest:
            raise ValueError('Runtime input identity drift')
    for relative, info in pins['models'].items():
        root = Path('/kaggle/input') / relative
        if sha(root / 'model.safetensors.index.json') != info['index_sha256']:
            raise ValueError('Model index drift')
        for item in info['weight_files']:
            if (root / item['name']).stat().st_size != item['bytes']:
                raise ValueError('Model shard missing or size drift')


def verify_installed_wheel(wheel, distribution):
    import importlib.metadata
    import importlib.util
    dist = importlib.metadata.distribution(distribution)
    from packaging.requirements import Requirement
    for text in getattr(dist, 'requires', None) or []:
        requirement = Requirement(text)
        if requirement.marker is None or requirement.marker.evaluate({'extra': ''}):
            if not requirement.specifier.contains(importlib.metadata.version(requirement.name), prereleases=True):
                raise ValueError('Installed ARC dependency is incompatible')
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.endswith('.py') and '.dist-info/' not in name:
                installed = Path(dist.locate_file(name))
                if installed.read_bytes() != archive.read(name):
                    raise ValueError('Installed ARC source differs from verified wheel')
                if name.endswith('/__init__.py') and name.count('/') == 1:
                    module = name.split('/')[0]
                    spec = importlib.util.find_spec(module)
                    if spec is None or Path(spec.origin).resolve() != installed.resolve():
                        raise ValueError('Installed ARC module is shadowed')


async def hidden_worker(package, private, budget, working):
    from entry_policy import CELLS
    budget.require()
    verify_inputs(json.loads((package / 'input-pins.json').read_text()))
    bundle = prepare_source(package, private,
        Path('/kaggle/input/datasets/dfranzen/taaf-kaggle-source-bundle-copy'))
    namespace = {'__name__': '__entry_policy__', 'budget': budget, 'PRIVATE': private,
                 'ENTRY_BUNDLE': bundle}
    current = asyncio.current_task()
    loop = asyncio.get_running_loop()
    def request_stop():
        # Cancelling during bm.run invokes its game finalization; setup can also
        # block synchronously, which is bounded by the independent parent.
        current.cancel()
    loop.add_signal_handler(signal.SIGUSR1, request_stop)
    try:
        for index in (4, 6, 8, 10, 12, 14, 16):
            budget.require()
            exec(compile(CELLS[index], f'entry-policy-cell-{index}', 'exec'), namespace)
        # Install scratch stays on disk. Only inference/runtime-state scratch
        # uses owned RAM; Python may have cached its earlier temporary directory.
        import tempfile
        tempfile.tempdir = str(private)
        os.environ['TMPDIR'] = str(private)
        # Verify actual module origins before allowing model/game deserialization
        # is handled in the generated cell14 before its pickle.load calls.
        bm, target = namespace['bm'], namespace['target']
        import arc_agi
        import taaf.game_api
        import urllib.request
        base = os.environ.setdefault('ARC_BASE_URL', 'http://gateway:8001/')
        os.environ.setdefault('ARC_API_KEY', 'test-key-123')
        wait_gateway(base, budget, urllib.request.urlopen)
        bm.games = competition_games(arc_agi, taaf.game_api, base, budget)
        budget.require()
        try:
            await bm.run(soft_end_time=budget.soft_datetime(), runtime_environment=target,
                         minimal_diagnostics=True)
        except asyncio.CancelledError:
            # Caller-cancellation is expected at the fixed parent work deadline;
            # benchmark re-raises only after finalizing games.
            if budget.remaining() > 0:
                raise
        finish_benchmark(bm)
    finally:
        loop.remove_signal_handler(signal.SIGUSR1)
        # Parent also kills the entire owned worker group, including a server
        # whose leader exited early. No PID discovered from logs is trusted.
        proc = namespace.get('proc')
        if proc is not None and proc.poll() is None:
            proc.terminate()


if __name__ == '__main__':
    private = Path(os.environ['ARC_ENTRY_PRIVATE_RUNTIME'])
    budget = Budget(float(os.environ['ARC_ENTRY_STARTED']), float(os.environ['ARC_ENTRY_WALL_STARTED']),
                    float(os.environ['ARC_ENTRY_TOTAL']), float(os.environ['ARC_ENTRY_RESERVE']))
    asyncio.run(hidden_worker(Path(__file__).parent, private, budget,
                              Path(os.environ['ARC_ENTRY_WORKING'])))
