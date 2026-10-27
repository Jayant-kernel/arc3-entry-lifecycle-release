"""Audited diagnostics-only source adaptation for the separate entry.

This module inspects text; it never imports the inspected framework. Call only
on an isolated, already verified effective ``src`` tree before deserialization.
Every replacement is gated by ARC_ENTRY_PRIVATE_RUNTIME at execution time.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
from pathlib import Path


SOLVER = "ARC3-Inference/inference/framework/solver.py"
AGENT = "ARC3-Inference/inference/agent/tool_agent.py"
BENCHMARK = "tufa-arc-agi-framework/src/taaf/benchmark.py"
SANDBOX = "ARC3-Inference/inference/agent/python_tool_sandbox.py"
EXPECTED = {
    SOLVER: "3c83c4706082c50677cc29c787bb0408dcc27361088a300ba347ba932c547823",
    AGENT: "485ef8a98308654b9dbb69535bc3c6ed3723c80bbcd5a4538e3ce181e6fda615",
    BENCHMARK: "d273e8056f83a3d1557d31c50c9716ed205258c8b1ba31747367a743d51c9497",
    SANDBOX: "c2208578220862aceb352138b9c3a3bb7347f1e6a4ad09d1d9cb3f2ee3507477",
}
FLAG = '__import__("os").environ.get("ARC_ENTRY_PRIVATE_RUNTIME")'


def _arc_entry_remaining():
    """Private lifecycle clock; invalid or missing deadline fails closed."""
    import math
    import os
    import time
    end = float(os.environ["ARC_ENTRY_WORK_END"])
    if not math.isfinite(end):
        raise ValueError("Invalid private entry deadline")
    return max(0.0, end - time.monotonic())


def private_state_path(name: str):
    """Require an owned, private tmpfs directory; never fall back to disk.

    This function is also inserted verbatim into solver.py, so its imports are
    deliberately local. The supervisor owns creation and removal of this root.
    """
    import os
    from pathlib import Path
    import stat

    raw = os.environ.get("ARC_ENTRY_PRIVATE_RUNTIME", "")
    root = Path(raw)
    if (not raw or os.name != "posix" or not root.is_absolute()
            or root.is_symlink() or root.parent != Path("/dev/shm")
            or not root.name.startswith("arc-entry-")):
        raise ValueError("Private runtime must be an owned /dev/shm/arc-entry-* directory")
    resolved = root.resolve(strict=True)
    metadata = resolved.stat()
    if (resolved != root or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077):
        raise ValueError("Private runtime ownership or permissions are invalid")
    mounts = Path("/proc/mounts").read_text(encoding="utf-8").splitlines()
    if not any(len(parts := line.split()) >= 3
               and parts[1:3] == ["/dev/shm", "tmpfs"] for line in mounts):
        raise ValueError("Private runtime is not the expected tmpfs mount")
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError("Private runtime filename must be a basename")
    target = root / name
    if target.is_symlink() or target.resolve().parent != root:
        raise ValueError("Private runtime file escapes its owned directory")
    return target


def _guard(source: str, qualified: str) -> str:
    """Insert an opt-in early return after the existing docstring, if any."""
    nodes = ast.parse(source).body
    for component in qualified.split("."):
        matches = [node for node in nodes if getattr(node, "name", None) == component]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one diagnostic function: {qualified}")
        node = matches[0]
        nodes = node.body
    first = nodes[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        first = nodes[1]
    lines = source.splitlines(keepends=True)
    prefix = " " * first.col_offset
    lines.insert(first.lineno - 1, f"{prefix}if {FLAG}:\n{prefix}    return\n")
    return "".join(lines)


def _once(source: str, old: str, new: str) -> str:
    if source.count(old) == 0 and "\r\n" in source:
        old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
    if source.count(old) != 1:
        raise ValueError("Diagnostic source anchor drift")
    return source.replace(old, new, 1)


def adapted_text(relative: str, original: bytes) -> tuple[bytes, list[str]]:
    """Verify known effective bytes and return adapted bytes plus audit labels."""
    if relative not in EXPECTED or hashlib.sha256(original).hexdigest() != EXPECTED[relative]:
        raise ValueError(f"Effective source hash mismatch: {relative}")
    source = original.decode("utf-8")
    changes: list[str] = []
    guards = {
        SOLVER: ["_write_transcript_html", "_HarnessGameSession._write_analysis_html",
                 "_HarnessGameSession.write_viewer_payload", "_HarnessGameSession._append_initial_viewer_event",
                 "_HarnessGameSession._append_analysis_viewer_event", "_HarnessGameSession._append_action_viewer_event"],
        AGENT: ["_append_transcript_section", "_append_request_snapshot", "_write_prompt_log_snapshot"],
        BENCHMARK: ["Benchmark._save_json", "Benchmark._save_intermediate_states", "Benchmark._save_games",
                    "Benchmark._save_solver", "Benchmark._generate_diagnostics"],
        SANDBOX: [],
    }[relative]
    for name in guards:
        source = _guard(source, name)
        changes.append(f"opt-in diagnostic early return: {name}")
    if relative == SOLVER:
        source = _once(source,
                       "    def soft_time_remaining_seconds(self) -> float | None:\n",
                       "    def soft_time_remaining_seconds(self) -> float | None:\n"
                       f"        if {FLAG}:\n"
                       "            return _arc_entry_remaining()\n")
        source = _once(source, "    def should_stop(self) -> bool:\n",
                       "    def should_stop(self) -> bool:\n"
                       f"        if {FLAG} and _arc_entry_remaining() <= 0:\n"
                       "            return True\n")
        source = _once(source,
                       '            state_path = self._artifacts_dir() / f"{run_stem}_{RUNTIME_STATE_FILENAME}"\n',
                       '            state_path = (private_state_path(f"{run_stem}_{RUNTIME_STATE_FILENAME}")\n'
                       f'                          if {FLAG} else self._artifacts_dir() / f"{{run_stem}}_{{RUNTIME_STATE_FILENAME}}")\n')
        source = _once(source,
                       '            transcript_path = self._transcripts_dir() / f"{run_stem}.txt"\n',
                       f'            transcript_path = (Path(__import__("os").devnull) if {FLAG}\n'
                       '                               else self._transcripts_dir() / f"{run_stem}.txt")\n')
        source = _once(source,
                       '        self.transcript_path.parent.mkdir(parents=True, exist_ok=True)\n'
                       '        self.transcript_path.touch(exist_ok=True)\n',
                       f'        if not {FLAG}:\n'
                       '            self.transcript_path.parent.mkdir(parents=True, exist_ok=True)\n'
                       '            self.transcript_path.touch(exist_ok=True)\n')
        # Append a local-import-only helper; no imports or runtime side effects.
        source += "\n\n" + inspect.getsource(private_state_path)
        changes += ["runtime state moved to validated owned tmpfs", "transcript path uses null device; no touch"]
        source += "\n\n" + inspect.getsource(_arc_entry_remaining)
        changes.append("private monotonic soft hint and game stop boundary")
    if relative == AGENT:
        source = _once(source,
                       '        analyzer_log = transcript_path or (state_path.parent / f"{state_path.stem}_analyzer.txt")\n',
                       f'        analyzer_log = (Path(__import__("os").devnull) if {FLAG} else\n'
                       '                        transcript_path or (state_path.parent / f"{state_path.stem}_analyzer.txt"))\n')
        changes.append("direct transcript header uses null device; no None fallback")
        source = _once(source,
                       "        def post_chat(request_payload: dict[str, Any]) -> requests.Response:\n",
                       "        def post_chat(request_payload: dict[str, Any]) -> requests.Response:\n"
                       f"            if {FLAG} and _arc_entry_remaining() <= 0:\n"
                       '                raise TimeoutError("Entry request deadline exhausted")\n')
        source += "\n\n" + inspect.getsource(_arc_entry_remaining)
        changes.append("reject new HTTP request attempts after private monotonic work end")
    if relative == SANDBOX:
        source = _once(source, "                start_new_session=True,\n",
                       f"                start_new_session=not bool({FLAG}),\n")
        source = _once(source,
                       "def _kill_process_group(process: subprocess.Popen[str]) -> None:\n",
                       "def _kill_process_group(process: subprocess.Popen[str]) -> None:\n"
                       f"    if {FLAG}:\n"
                       "        try:\n"
                       "            process.kill()\n"
                       "        except OSError:\n"
                       "            pass\n"
                       "        return\n")
        changes += ["sandbox stays in supervisor-owned worker process group",
                    "per-tool timeout kills only its tool child in private mode"]
    compile(source, relative, "exec")
    return source.encode("utf-8"), changes


def adapt_sources(source_root: Path) -> dict[str, dict]:
    """Adapt an isolated tree after validating every touched input, before writes.

    Callers must first verify the full effective tree against the source gate.
    This function pins all touched files, preserves all other files, and refuses
    repeated application. Frozen evidence trees and reference clones are inputs,
    never appropriate destinations.
    """
    source_root = Path(source_root)
    prepared = {}
    for relative in EXPECTED:
        path = source_root / relative
        if path.is_symlink() or source_root.resolve() not in path.resolve().parents:
            raise ValueError("Diagnostic source target escapes isolated tree")
        original = path.read_bytes()
        result, changes = adapted_text(relative, original)
        prepared[relative] = (path, original, result, changes)
    report = {}
    for relative, (path, original, result, changes) in prepared.items():
        path.write_bytes(result)
        report[relative] = {"before_sha256": hashlib.sha256(original).hexdigest(),
                            "after_sha256": hashlib.sha256(result).hexdigest(), "changes": changes}
    return report
