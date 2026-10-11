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

TOOL_CALL_BUDGET = 40  # tool calls allowed in one user turn; past this the turn stops and says what is left
BUDGET_EXHAUSTED_RESULT = "Error: the tool-call budget for this turn is used up. Stop calling tools and tell the user what is left to do."

RATE_LIMIT_COOLDOWN_SEC = 60
RATE_LIMIT_RETRIES = 3
# Words that say the reply made a change, such as 'I implemented the fix'
# A reply that says a file was changed: a change verb near the word "file" or a source-like filename, in either order
FILE_EDIT_CLAIM = re.compile(
    r"\b(edited|modified|updated|changed|wrote|written|created|added|fixed|refactored|implemented)\b[^.\n]{0,60}"
    r"(\bfiles?\b|\S+\.(py|md|js|ts|json|txt|html|css|toml|yaml|yml|sh)\b)"
    r"|\bfiles?\b[^.\n]{0,40}\b(edited|modified|updated|changed|written|created|added)\b",
    re.I,
)
_5XX_BACKOFF_SEC = (1, 2, 4)
# Turns kept verbatim by /compress; everything older is replaced by a summary
KEEP_TURNS = 4
SUMMARY_REQUEST = (
    "Summarize the conversation above so it can stand in for those messages. "
    "Keep the user's goals, decisions, file paths, and open questions. Reply with the summary only."
)

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

    def _request_with_retries(self, payload=None):
        if payload is None:
            payload = self._payload()
        rate_limit_retries = 0
        server_retries = 0
        while True:
            status, body = self._generate(payload)
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
        self.tool_calls = 0
        try:
            self._run_turn(prompt)
        except (Exception, KeyboardInterrupt):  # Ctrl+C stops the turn; its messages are dropped
            del self.history[start:]
            raise
        self._save_session(label or prompt)

    def _turn_starts(self) -> list:
        """Indexes of the messages that begin a user turn: user messages with text, not tool results."""
        return [i for i, message in enumerate(self.history)
                if message.get("role") == "user" and any("text" in part for part in message.get("parts", []))]

    def compress(self, keep: int = KEEP_TURNS) -> int:
        """Replace all but the last `keep` turns with a summary the model writes. Returns how many turns were summarized,
        or 0 if the chat is short enough already. If the summary request fails, the history is left as it was."""
        starts = self._turn_starts()
        if len(starts) <= keep:
            return 0
        split = starts[-keep]
        older = self.history[:split]
        summary_request = {
            "contents": older + [{"role": "user", "parts": [{"text": SUMMARY_REQUEST}]}],
            "systemInstruction": {"parts": [{"text": self.system_instruction}]},
            "generationConfig": {"temperature": 0.2},
        }
        summary = self._request_with_retries(summary_request).text.strip()
        if not summary:
            raise GeminiError(0, "The model returned an empty summary. The conversation is unchanged.")

        self.history = [
            {"role": "user", "parts": [{"text": f"Summary of the earlier part of this conversation:\n{summary}"}]},
            {"role": "model", "parts": [{"text": "Understood. I will continue from this summary."}]},
        ] + self.history[split:]
        # The footer's count should drop now, not after the next answer. Keep the old count if it cannot be fetched.
        count = gemini.count_tokens(self.model, self.api_key, {
            "contents": self.history,
            "systemInstruction": {"parts": [{"text": self.system_instruction}]},
        })
        if count is not None:
            self.prompt_token_count = count
        if self.session is not None:
            self._save_session("")
        return len(starts) - keep

    def _run_turn(self, prompt: str):
        if self.verbose:
            print(blue("thinking..."))
        reply = self._send([{"text": expand_mentions(prompt)}])
        searched = False
        refused = False  # the budget ran out and the model has been told to stop

        while True:
            # Check if model wants to call functions
            if reply.function_calls:
                if refused:
                    # The model kept asking for tools after being told to stop: end the turn here
                    note = "Stopped: the tool-call budget for this turn ran out. Ask me to continue to pick it up."
                    self.history.append({"role": "model", "parts": [{"text": note}]})
                    print(yellow(note))
                    break
                # Run every call in this batch, then send all results back in one request
                parts = []
                for name, args in reply.function_calls:
                    if self.verbose:
                        print(yellow(f"⚡ Executing tool: {name}({args})"))

                    self.tool_calls += 1
                    if self.tool_calls > TOOL_CALL_BUDGET:
                        refused = True
                        result = BUDGET_EXHAUSTED_RESULT
                        parts.append({"functionResponse": {"name": name, "response": {"result": result}}})
                        continue

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
                    if not self.last_edits and FILE_EDIT_CLAIM.search(reply.text):
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
        return f"{where} | {self.model} | {ctx} | files written: {written} | tool calls: {self.tool_calls} | {view}"

