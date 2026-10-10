import difflib
import os
import re
import subprocess
import time
from pathlib import Path

from . import gemini, sessions
from .config import get_api_key, get_model_name
from .context import load_contexts
from .gemini import GeminiError
from .markdown import render as render_markdown
from .mcp_client import get_manager
from .memory import MEMORY_GUIDANCE
from .mentions import expand_mentions
from .skills import enabled_skills_prompt
from .term import blue, dim, green, red, yellow
from .tools import all_declarations, execute_tool

def _read_text_or_none(path: Path):
    """File contents, or None if the file does not exist or cannot be read as text."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

def _git_branch(cwd: Path) -> str:
    """Current git branch for cwd, or '' outside a repository or on error."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""

# Tool results that start with one of these count as failures in the compact view
FAILURE_PREFIXES = ("Error", "Web search failed")

RATE_LIMIT_COOLDOWN_SEC = 60
RATE_LIMIT_RETRIES = 3
# Words that say the reply made a change, such as 'I implemented the fix'
CHANGE_CLAIM = re.compile(r"\b(implemented|edited|modified|changed|updated|added|created|wrote|fixed|refactored)\b", re.I)
_5XX_BACKOFF_SEC = (1, 2, 4)

class Agent:
    # Compact view by default; the REPL flips this with Ctrl+O. Affects only what is printed, not the chat.
    verbose = False

    def __init__(self):
        self.api_key = get_api_key()
        if not self.api_key:
            raise ValueError("API key not found.")
        self.model = get_model_name()
        get_manager()  # connect MCP servers at startup, not on the first request

        # Build system instruction with contexts
        base_instruction = (
            "You are Code Shellie, an expert AI software engineering agent. "
            "You have access to local files and shell execution tools. "
            "Always inspect, test, and explain your changes clearly. "
            f"{MEMORY_GUIDANCE}"
        )
        extra_context = load_contexts()
        if extra_context:
            base_instruction += f"\n\n{extra_context}"

        self._base_instruction = base_instruction
        self.system_instruction = self._build_instruction()
        self.history = []
        self.last_edits = {}  # file path -> contents before the last turn's first write, or None if the file was new
        self.session = None  # metadata of the saved session this chat writes to; None until the first turn completes
        self.prompt_token_count = 0
        self.total_token_count = 0
        self.last_answer = ""
        self.model_limit = gemini.get_input_limit(self.model, self.api_key)

    def _build_instruction(self) -> str:
        """Base instruction, project/system context, then the enabled skills."""
        skills = enabled_skills_prompt()
        if skills:
            return f"{self._base_instruction}\n\n{skills}"
        return self._base_instruction

    def refresh_skills(self):
        """Rebuild the system prompt after skills change. Starts a fresh chat, like /model does."""
        self.system_instruction = self._build_instruction()
        self.reset_chat()

    def reset_chat(self):
        """Clear the conversation history. The saved session file, if any, is kept so it can still be resumed."""
        self.history = []
        self.session = None
        self.prompt_token_count = 0
        self.total_token_count = 0

    def discard_session(self):
        """Delete the current session file and clear the chat, so nothing is left to resume."""
        if self.session is not None:
            sessions.delete(self.session["id"])
        self.reset_chat()

    def restore(self, data: dict):
        """Continue a saved session: its history becomes the chat, and new turns are saved to the same file."""
        self.history = list(data["history"])
        self.session = {key: data[key] for key in ("id", "started", "cwd", "model", "description")}
        self.prompt_token_count = 0
        self.total_token_count = 0

    def _save_session(self, prompt: str):
        if self.session is None:
            self.session = {
                "id": sessions.new_session_id(),
                "started": time.time(),
                "cwd": os.getcwd(),
                "model": self.model,
                "description": sessions.describe(prompt),
            }
        try:
            sessions.save({**self.session, "updated": time.time(), "history": self.history})
        except OSError as e:
            print(yellow(f"Could not save the session: {e}"))

    def _payload(self) -> dict:
        return {
            "contents": self.history,
            "systemInstruction": {"parts": [{"text": self.system_instruction}]},
            "tools": [{"functionDeclarations": all_declarations()}],
            "generationConfig": {"temperature": 0.2},
        }

    def _generate(self, payload: dict):
        """One request to the model. Returns (status, body). Separate so tests can replace it."""
        return gemini.generate(self.model, self.api_key, payload)

    def _send(self, parts):
        """Append a user turn (text or function responses), then request the model's reply.

        Policy (see docs/gemini_429_observations.md in shellie):
        Per-minute 429 (RPM or input tokens): always cool down for RATE_LIMIT_COOLDOWN_SEC, up to RATE_LIMIT_RETRIES times.
        RPD: give up. 5xx: retry with exponential backoff (1s, 2s, 4s), then give up.
        Giving up raises GeminiError, which the REPL catches so the session continues.
        """
        self.history.append({"role": "user", "parts": parts})
        try:
            reply = self._request_with_retries()
        except (Exception, KeyboardInterrupt):  # Ctrl+C during a request also drops the turn
            self.history.pop()
            raise
        if reply.content:  # a blocked reply has no content; keep the history well-formed
            self.history.append(reply.content)
        self.prompt_token_count = reply.prompt_tokens or self.prompt_token_count
        self.total_token_count += reply.total_tokens
        return reply

    def _request_with_retries(self):
        rate_limit_retries = 0
        server_retries = 0
        while True:
            status, body = self._generate(self._payload())
            if status == 200:
                return gemini.parse_response(body)
            message = gemini.error_message(body, status)
            if status == 429:
                if "PerDay" in str(body):
                    print(red("Daily quota (RPD) reached. Try again tomorrow."))
                    raise GeminiError(status, message, body)
                if rate_limit_retries >= RATE_LIMIT_RETRIES:
                    print(red(f"Still rate limited after {RATE_LIMIT_RETRIES} cooldowns. Stopping this turn."))
                    raise GeminiError(status, message, body)
                rate_limit_retries += 1
                print(yellow(
                    f"AI is overloaded. Wait a minute ({rate_limit_retries}/{RATE_LIMIT_RETRIES})"
                ))
                time.sleep(RATE_LIMIT_COOLDOWN_SEC)
            elif status >= 500 and server_retries < len(_5XX_BACKOFF_SEC):
                delay = _5XX_BACKOFF_SEC[server_retries]
                server_retries += 1
                print(yellow(f"Server error {status}. Retrying in {delay}s..."))
                time.sleep(delay)
            else:
                raise GeminiError(status, message, body)

    def run_turn(self, prompt: str, label: str = None):
        """Run one user request to completion. On failure, the turn is removed from history so the session stays valid.
        A completed turn is saved to the session file, described by label (what the user typed) or else the prompt."""
        start = len(self.history)
        self.last_edits = {}
        try:
            self._run_turn(prompt)
        except (Exception, KeyboardInterrupt):  # Ctrl+C stops the turn; its messages are dropped
            del self.history[start:]
            raise
        self._save_session(label or prompt)

    def _run_turn(self, prompt: str):
        if self.verbose:
            print(blue("thinking..."))
        reply = self._send([{"text": expand_mentions(prompt)}])
        searched = False

        while True:
            # Check if model wants to call functions
            if reply.function_calls:
                # Run every call in this batch, then send all results back in one request
                parts = []
                for name, args in reply.function_calls:
                    if self.verbose:
                        print(yellow(f"⚡ Executing tool: {name}({args})"))

                    # Snapshot the file before a write so /diff can show what this turn changed
                    target = Path(args.get("file_path", "")).expanduser() if name == "write_file" else None
                    before = _read_text_or_none(target) if target else None

                    result = execute_tool(name, args)
                    searched = searched or name == "execute_web_search"
                    failed = str(result).startswith(FAILURE_PREFIXES)
                    if target and not failed:
                        self.last_edits.setdefault(str(target), before)
                    if self.verbose:
                        print(dim(f"Result: {str(result)[:200]}..."))
                    elif failed:
                        print(red(f"{name} failed: {str(result)[:200]}"))
                    else:
                        if name == "remember":
                            print(dim(str(result)))  # the saved fact, so the user can review it
                        else:
                            print(dim(f"{name} called"))
                        if name == "write_file":
                            print(dim(f"{args.get('file_path', '')} edited"))

                    parts.append({"functionResponse": {"name": name, "response": {"result": result}}})
                reply = self._send(parts)
            else:
                if reply.text:
                    self.last_answer = reply.text
                    print(f"\n{green('Code Shellie:')}\n")
                    print(render_markdown(reply.text))
                    print()
                    if searched and gemini.last_sources:
                        print(dim("Sources: type /sources for the full links."))
                    if not self.last_edits and CHANGE_CLAIM.search(reply.text):
                        print(yellow("Warning: this reply describes changes, but no file was written this turn. Check with /diff or git status."))
                    print(dim(self._footer()))
                break

    def edits_diff(self) -> str:
        """Unified diff of each file the last turn wrote, from its contents before the turn to its contents now. Empty if nothing changed."""
        chunks = []
        for path, before in self.last_edits.items():
            after = _read_text_or_none(Path(path))
            if after == before:
                continue
            diff = difflib.unified_diff(
                (before or "").splitlines(keepends=True),
                (after or "").splitlines(keepends=True),
                fromfile=f"a/{path}" if before is not None else "/dev/null",
                tofile=f"b/{path}" if after is not None else "/dev/null",
            )
            chunks.append("".join(diff))
        return "\n".join(chunk for chunk in chunks if chunk)

    def _footer(self) -> str:
        """Status line under each answer: model, working directory, git branch, and context usage."""
        cwd = Path.cwd()
        home = str(Path.home())
        path = str(cwd)
        if path == home or path.startswith(home + os.sep):
            path = "~" + path[len(home):]
        branch = _git_branch(cwd)
        where = f"{path} ({branch})" if branch else path

        if self.model_limit:
            percent = (self.prompt_token_count / self.model_limit) * 100
            ctx = f"ctx {self.prompt_token_count:,} / {self.model_limit:,} ({percent:.1f}%)"
        else:
            ctx = f"ctx {self.prompt_token_count:,}"
        view = "verbose" if self.verbose else "compact"
        written = len(self.last_edits)  # files this turn wrote successfully, so a claimed edit with 0 is visible
        return f"{where} | {self.model} | {ctx} | files written: {written} | {view}"

