"""Runs the run_script tool: a Python script the model writes, executed in a child process.
Only what the script prints goes back into the chat. The child gets small helpers for listing, searching,
reading and editing files. It never imports code_shellie, so Gemini and MCP code are not loaded there.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from typing import Dict, Optional, Tuple

from . import shell

TIMEOUT_SEC = 60
SCRIPT_OUTPUT_LIMIT = 8_000
TRACEBACK_LINES = 30  # last lines of a traceback sent back to the model

CODE_MODE_GUIDANCE = (
    "For work across several files (many searches, listings, or the same edit to several files), use run_script "
    "and print only a compact summary. For a single read or edit, use the normal file tools."
)

# Helpers available as globals in every script. Paths are relative to the working directory.
_HELPERS = r'''
import json
import os
import pathlib
import re
import subprocess

_EDIT_LOG = os.environ.get("CODESH_EDIT_LOG", os.devnull)
_EDITS = {}


def _path(path):
    return pathlib.Path(path).expanduser()


def _visible(name):
    return not name.startswith(".") and name not in SKIPPED_DIRS


def ls(path=".", depth=1):
    """Entries under path, down to depth levels. Directories end with '/'."""
    depth = min(max(int(depth or 1), 1), MAX_LIST_DEPTH)
    result = []

    def walk(directory, level):
        for item in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name)):
            if not _visible(item.name):
                continue
            if item.is_dir():
                result.append(str(item) + "/")
                if level < depth:
                    walk(item, level + 1)
            else:
                result.append(str(item))

    walk(_path(path), 1)
    return result


def find(glob="**/*", path="."):
    """Files under path matching glob (pathlib syntax, e.g. '**/*.py'). Hidden and dependency folders are skipped."""
    root = _path(path)
    return [str(item) for item in sorted(root.glob(glob))
            if item.is_file() and all(_visible(part) for part in item.parts[len(root.parts):])]


def grep(pattern, path=".", glob=None, limit=200):
    """Lines matching the regular expression pattern, as (file, line number, text) tuples. Binary files are skipped."""
    regex = re.compile(pattern)
    if _path(path).is_file():
        files = [str(_path(path))]
    else:
        files = find(glob or "**/*", path)
    matches = []
    for name in files:
        try:
            lines = pathlib.Path(name).read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, start=1):
            if regex.search(line):
                matches.append((name, number, line.strip()))
                if len(matches) >= limit:
                    return matches
    return matches


def read(path, start=None, end=None):
    """Text of a file, or only lines start to end (1-based, inclusive)."""
    text = _path(path).read_text(encoding="utf-8")
    if start is None and end is None:
        return text
    lines = text.splitlines()
    first = max(int(start or 1), 1)
    last = min(int(end or len(lines)), len(lines))
    return "\n".join(lines[first - 1:last])


def _remember(target):
    """Keep what a file held before the script first wrote it, so /diff can show the change."""
    key = os.path.abspath(target)
    if key not in _EDITS:
        _EDITS[key] = target.read_text(encoding="utf-8") if target.exists() else None
        with open(_EDIT_LOG, "w", encoding="utf-8") as f:
            json.dump(_EDITS, f)


def write(path, content):
    """Write content to a file, creating parent folders if needed."""
    target = _path(path)
    _remember(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def edit(path, old, new, count=1):
    """Replace old with new in a file. count is the number of occurrences expected (None replaces all).
    Raises ValueError if old is not found or the count differs. Returns the number of replacements."""
    target = _path(path)
    text = target.read_text(encoding="utf-8")
    found = text.count(old) if old else 0
    if found == 0:
        raise ValueError("text to replace not found in {}".format(path))
    if count is not None and found != count:
        raise ValueError("found {} occurrences in {}, expected {}".format(found, path, count))
    _remember(target)
    target.write_text(text.replace(old, new), encoding="utf-8")
    return found


def sh(command):
    """Run a command with /bin/sh and return its combined output. A non-zero exit code is appended."""
    proc = subprocess.run(["/bin/sh", "-c", command], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    output = proc.stdout
    if proc.returncode:
        output += "\n[Exit code: {}]".format(proc.returncode)
    return output

'''

# Runs the user's script, and prints only the traceback frames that belong to it
_LAUNCHER = r'''
import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
with open(sys.argv[1], encoding="utf-8") as _script:
    _source = _script.read()
try:
    exec(compile(_source, "<script>", "exec"), globals())
except Exception as _error:
    _frames = [frame for frame in traceback.extract_tb(_error.__traceback__) if frame.filename == "<script>"]
    sys.stderr.write("".join(traceback.format_list(_frames) + traceback.format_exception_only(type(_error), _error)))
    sys.exit(1)
'''


def _child_code() -> str:
    # Imported here because tools.py imports this module at the top
    from .tools import MAX_LIST_DEPTH, SKIPPED_DIRS
    settings = "SKIPPED_DIRS = {!r}\nMAX_LIST_DEPTH = {!r}\n".format(SKIPPED_DIRS, MAX_LIST_DEPTH)
    return settings + _HELPERS + _LAUNCHER


def _limit(text: str) -> str:
    if len(text) <= SCRIPT_OUTPUT_LIMIT:
        return text
    return text[:SCRIPT_OUTPUT_LIMIT] + "\n... (output truncated; print less, e.g. counts or only matching lines)"


def _failure_text(stdout: str, stderr: str, returncode: int) -> str:
    tail = "\n".join(stderr.strip().splitlines()[-TRACEBACK_LINES:]) or "[Exit code: {}]".format(returncode)
    text = "Error: script failed:\n" + tail
    if stdout.strip():
        text += "\nOutput before the failure:\n" + stdout.strip()
    return _limit(text)


def _execute(script_path: str, edit_log: str) -> str:
    env = shell._child_env()
    env["CODESH_EDIT_LOG"] = edit_log
    try:
        proc = subprocess.Popen(
            [sys.executable, "-I", "-c", _child_code(), script_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,  # own process group, so a timeout also stops grandchildren
            env=env,
            encoding="utf-8",
            errors="replace",
        )
        try:
            stdout, stderr = proc.communicate(timeout=TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            shell._kill_group(proc, signal.SIGKILL)
            proc.communicate()
            return "Error: script timed out after {} seconds.".format(TIMEOUT_SEC)

        if proc.returncode != 0:
            return _failure_text(stdout, stderr, proc.returncode)
        output = stdout.strip()
        return _limit(output) if output else "[Script ran with no output]"
    except Exception as e:
        return "Error running script: {}".format(e)


def _read_edits(edit_log: str) -> Dict[str, Optional[str]]:
    if not os.path.exists(edit_log):
        return {}
    with open(edit_log, encoding="utf-8") as f:
        return json.load(f)


def run(code: str) -> Tuple[str, Dict[str, Optional[str]]]:
    """Run a script and return (output for the model, {absolute path: contents before its first write, or None if new}).
    Edits are returned even when the script fails or times out, because the writes already happened."""
    workdir = tempfile.mkdtemp(prefix="codesh-script-")
    try:
        script_path = os.path.join(workdir, "script.py")
        edit_log = os.path.join(workdir, "edits.json")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)
        output = _execute(script_path, edit_log)
        return output, _read_edits(edit_log)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
