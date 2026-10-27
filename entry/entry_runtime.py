"""Entry lifecycle only. Ordinary saves never invoke hidden setup."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time


@dataclass(frozen=True)
class Budget:
    started: float
    wall_started: float
    total: float = 32400.0
    reserve: float = 600.0

    def __post_init__(self):
        if not all(math.isfinite(x) for x in (self.started, self.wall_started, self.total, self.reserve)):
            raise ValueError('Nonfinite entry budget')
        if not 0 < self.reserve < self.total:
            raise ValueError('Invalid entry reserve')

    @property
    def work_end(self):
        return self.started + self.total - self.reserve

    @property
    def hard_end(self):
        return self.started + self.total

    def remaining(self, now=None):
        return max(0.0, self.work_end - (time.monotonic() if now is None else now))

    def require(self, seconds=0.0):
        if self.remaining() <= seconds:
            raise TimeoutError('Entry work deadline exhausted')

    def soft_datetime(self):
        # Current wall time plus monotonic remaining, never wall_started + total.
        return datetime.now(timezone.utc) + timedelta(seconds=self.remaining())


def rerun_flag(environ):
    return environ.get('KAGGLE_IS_COMPETITION_RERUN', '').strip().lower() in {'1', 'true'}


def ordinary_output(working):
    import pandas as pd
    path = Path(working) / 'submission.parquet'
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([['1_0', '1', True, 1]],
                 columns=['row_id', 'game_id', 'end_of_game', 'score']).to_parquet(path, index=False)
    return path


def competition_games(arc, api, base_url, budget):
    budget.require()
    spec = api.ArcadeSpec(operation_mode=arc.OperationMode.COMPETITION,
                          arc_base_url=base_url, environments_dir='')
    arcade = arc.Arcade(operation_mode=arc.OperationMode.COMPETITION,
                        arc_base_url=base_url, environments_dir='')
    ids = [item.game_id for item in arcade.available_environments]
    budget.require()
    if (not ids or any(not isinstance(x, str) or not x.strip() for x in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('Invalid competition roster')
    return [api.GameAPI(env_name=x, arcade_spec=spec) for x in ids]


def wait_gateway(url, budget, opener, sleeper=time.sleep):
    while True:
        budget.require()
        try:
            with opener(url.rstrip('/') + '/api/games', timeout=min(10, budget.remaining())) as response:
                budget.require()
                if response.status == 200:
                    return
        except TimeoutError:
            budget.require()
        except Exception:
            pass
        budget.require()
        sleeper(min(5, budget.remaining()))


def finish_benchmark(bm):
    runs = getattr(bm, 'game_runs', [])
    if not runs or len(runs) != len(bm.games):
        raise RuntimeError('Incomplete benchmark lifecycle')
    if any(getattr(r, 'state', None) not in {'won', 'gave_up', 'cancelled'} for r in runs):
        raise RuntimeError('Benchmark left invalid terminal states')
    for run in runs:
        score = getattr(run, 'final_score', None)
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise RuntimeError('Benchmark finalization incomplete')


def cleanup_owned(proc, hard_end, grace=5.0):
    """Kill only the session/group created for our worker, even if its leader exited."""
    if os.name == 'posix':
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                break
            try:
                proc.wait(timeout=max(0.01, min(grace, hard_end - time.monotonic())))
            except subprocess.TimeoutExpired:
                pass
            # SIGKILL also reaches surviving group descendants after leader exit.
        if proc.poll() is None:
            proc.wait(timeout=max(0.01, hard_end - time.monotonic()))
    else:
        # Windows is a CPU test host only. Production entry requires Linux.
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=max(0.01, min(grace, hard_end - time.monotonic())))


def supervise(command, budget, env, *, cwd, popen=subprocess.Popen):
    budget.require()
    proc = popen(command, env=env, cwd=cwd, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, start_new_session=os.name == 'posix')
    timed_out = False
    try:
        while proc.poll() is None and budget.remaining() > 0:
            time.sleep(min(0.1, budget.remaining()))
        if proc.poll() is None:
            timed_out = True
            if os.name == 'posix':
                try:
                    os.kill(proc.pid, signal.SIGUSR1)
                except ProcessLookupError:
                    pass
            while proc.poll() is None and time.monotonic() < budget.hard_end - min(10, budget.reserve / 4):
                time.sleep(0.05)
        code = proc.poll()
    finally:
        cleanup_owned(proc, budget.hard_end)
    if code != 0:
        raise RuntimeError('Entry worker failed or exceeded shutdown deadline')
    return {'worker_exit': code, 'work_deadline_reached': timed_out}


def entry(environ, working, budget, hidden):
    if not rerun_flag(environ):
        ordinary_output(working)
        return {'mode': 'ordinary', 'placeholder': True}
    budget.require()
    # Real output belongs exclusively to the gateway. Never invoke ordinary_output.
    result = hidden(budget)
    if not (Path(working) / 'submission.parquet').is_file():
        raise RuntimeError('Gateway output absent; entry acceptance unverified')
    return result


def hidden_package(package, budget, working='/kaggle/working'):
    if os.environ.get('ARC3_SYSTEM_PROMPT_PREFIX', ''):
        raise RuntimeError('Entry requires the unchanged control prompt')
    if os.name != 'posix' or not Path('/dev/shm').is_dir():
        raise RuntimeError('Hidden entry requires Linux tmpfs')
    # Refuse a disk-backed /dev/shm rather than leave private state on a disk.
    if not any(line.split()[1:3] == ['/dev/shm', 'tmpfs']
               for line in Path('/proc/mounts').read_text().splitlines()):
        raise RuntimeError('Private runtime must reside on tmpfs')
    if shutil.disk_usage('/dev/shm').free < 256 * 1024 * 1024:
        raise RuntimeError('Insufficient private tmpfs capacity (minimum 256 MiB)')
    private = Path(tempfile.mkdtemp(prefix='arc-entry-', dir='/dev/shm'))
    private.chmod(0o700)
    try:
        # Sources contain no gameplay data. Generated package is copied to private RAM.
        for path in Path(package).iterdir():
            if path.is_file() and path.suffix in {'.py', '.json', '.patch'}:
                shutil.copyfile(path, private / path.name)
        env = dict(os.environ, ARC_ENTRY_PRIVATE_RUNTIME=str(private),
                   ARC_ENTRY_WORKING=str(working), ARC_ENTRY_STARTED=str(budget.started),
                   ARC_ENTRY_WALL_STARTED=str(budget.wall_started),
                   ARC_ENTRY_TOTAL=str(budget.total), ARC_ENTRY_RESERVE=str(budget.reserve),
                   ARC_ENTRY_WORK_END=str(budget.work_end),
                   PYTHONDONTWRITEBYTECODE='1')
        # Fresh disk-only installation prefix avoids trusting an old install
        # stamp. It contains runtime/caches, never hidden transcript/state.
        env['ARC_ENTRY_INSTALL'] = tempfile.mkdtemp(prefix='arc-entry-install-')
        return supervise([os.sys.executable, str(private / 'entry_worker.py')], budget, env, cwd=private)
    finally:
        # Only the exact newly-created owned RAM directory; no workspace paths.
        if private.parent != Path('/dev/shm') or not private.name.startswith('arc-entry-'):
            raise RuntimeError('Private cleanup target mismatch')
        shutil.rmtree(private)
