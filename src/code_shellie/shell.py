"""Runs the run_shell_command tool. Ported from shellie's core/shell.py, trimmed to what codesh uses:
the timeout with process-group kill, output truncation and a scrubbed child environment.
"""
from __future__ import annotations

import os
import signal
import subprocess
from typing import Dict

TIMEOUT_SEC = 60
OUTPUT_LIMIT = 50_000
SHELL = "/bin/sh"

# Secrets the child process should not inherit.
_SCRUBBED_ENV = ("GEMINI_API_KEY",)


def _child_env() -> Dict[str, str]:
    env = dict(os.environ)
    for key in _SCRUBBED_ENV:
        env.pop(key, None)
    return env


def _truncate(text: str) -> str:
    if len(text) <= OUTPUT_LIMIT:
        return text
    return text[:OUTPUT_LIMIT] + "\n... (output truncated at {} chars)".format(OUTPUT_LIMIT)


def _kill_group(proc: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def run_command(command: str) -> str:
    """Run command with /bin/sh and return its output, stderr and exit code as text."""
    try:
        proc = subprocess.Popen(
            [SHELL, "-c", command],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,  # own process group, so a timeout also stops grandchildren
            env=_child_env(),
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            _kill_group(proc, signal.SIGKILL)
            proc.communicate()
            return "Error: Command timed out after {} seconds.".format(TIMEOUT_SEC)

        output = stdout
        if stderr:
            output += "\nSTDERR:\n" + stderr
        if proc.returncode != 0:
            output += "\n[Exit code: {}]".format(proc.returncode)
        output = output.strip()
        return _truncate(output) if output else "[Command executed with no output]"
    except Exception as e:
        return "Error executing command: {}".format(e)
