import os
import subprocess
import time
from pathlib import Path
from google import genai
from google.genai import errors, types
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from .config import get_api_key, get_model_name
from .tools import TOOL_DECLARATIONS, execute_tool
from .context import load_contexts
from .mentions import expand_mentions
from .mcp_client import get_manager

console = Console()

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

RATE_LIMIT_COOLDOWN_SEC = 60
RATE_LIMIT_RETRIES = 3
_5XX_BACKOFF_SEC = (1, 2, 4)

class Agent:
    def __init__(self):
        api_key = get_api_key()
        if not api_key:
            raise ValueError("API key not found.")
        self.client = genai.Client(api_key=api_key)
        self.model = get_model_name()
        
        # Build system instruction with contexts
        base_instruction = (
            "You are Code Shellie, an expert AI software engineering agent. "
            "You have access to local files and shell execution tools. "
            "Always inspect, test, and explain your changes clearly."
        )
        extra_context = load_contexts()
        if extra_context:
            base_instruction += f"\n\n{extra_context}"
            
        self.system_instruction = base_instruction
        self.chat = self.client.chats.create(
            model=self.model,
            config=types.GenerateContentConfig(
                system_instruction=self.system_instruction,
                tools=[TOOL_DECLARATIONS, *get_manager().tool_declarations()],
                temperature=0.2,
            )
        )
        self.prompt_token_count = 0
        self.total_token_count = 0
        self.last_answer = ""
        self.model_limit = self._get_model_limit()

    def reset_chat(self):
        """Reset the conversation chat session while keeping client/model configuration."""
        self.chat = self.client.chats.create(
            model=self.model,
            config=types.GenerateContentConfig(
                system_instruction=self.system_instruction,
                tools=[TOOL_DECLARATIONS, *get_manager().tool_declarations()],
                temperature=0.2,
            )
        )
        self.prompt_token_count = 0
        self.total_token_count = 0

    def _get_model_limit(self):
        try:
            model_info = self.client.models.get(model=self.model)
            return model_info.input_token_limit
        except Exception:
            return None

    def _send(self, message):
        """Send a message, following the policy in shellie/docs/gemini_429_observations.md.

        Per-minute 429 (RPM or input tokens): always cool down for RATE_LIMIT_COOLDOWN_SEC, up to RATE_LIMIT_RETRIES times.
        RPD: give up (no fallback model here).
        5xx: retry with exponential backoff (1s, 2s, 4s), then give up.
        Giving up raises APIError, which the REPL catches so the session continues.
        """
        rate_limit_retries = 0
        server_retries = 0
        while True:
            try:
                response = self.chat.send_message(message)
                if response.usage_metadata:
                    self.prompt_token_count = response.usage_metadata.prompt_token_count
                    self.total_token_count += response.usage_metadata.total_token_count
                return response
            except errors.APIError as e:
                if e.code == 429:
                    if "PerDay" in str(e):
                        console.print("[bold red]Daily quota (RPD) reached. Try again tomorrow.[/bold red]")
                        raise
                    if rate_limit_retries >= RATE_LIMIT_RETRIES:
                        console.print(f"[bold red]Still rate limited after {RATE_LIMIT_RETRIES} cooldowns. Stopping this turn.[/bold red]")
                        raise
                    rate_limit_retries += 1
                    console.print(
                        f"[yellow]Rate limit hit. Cooling down for {RATE_LIMIT_COOLDOWN_SEC}s "
                        f"(attempt {rate_limit_retries}/{RATE_LIMIT_RETRIES})...[/yellow]"
                    )
                    time.sleep(RATE_LIMIT_COOLDOWN_SEC)
                elif e.code >= 500 and server_retries < len(_5XX_BACKOFF_SEC):
                    delay = _5XX_BACKOFF_SEC[server_retries]
                    server_retries += 1
                    console.print(f"[yellow]Server error {e.code}. Retrying in {delay}s...[/yellow]")
                    time.sleep(delay)
                else:
                    raise

    def run_turn(self, prompt: str):
        console.print(f"[bold blue]Thinking...[/bold blue]")
        response = self._send(expand_mentions(prompt))

        while True:
            # Check if model wants to call functions
            if response.function_calls:
                # Run every call in this batch, then send all results back in one request
                parts = []
                for function_call in response.function_calls:
                    name = function_call.name
                    args = function_call.args
                    console.print(f"[yellow]⚡ Executing tool: {name}({args})[/yellow]")

                    # Execute tool
                    result = execute_tool(name, args)
                    console.print(f"[dim]Result: {str(result)[:200]}...[/dim]")

                    parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=function_call.id,
                                name=name,
                                response={"result": result}
                            )
                        )
                    )
                response = self._send(parts)
            else:
                if response.text:
                    self.last_answer = response.text
                    console.print(f"\n[bold green]Code Shellie:[/bold green]\n")
                    console.print(Markdown(response.text))
                    console.print()
                    console.print(f"[dim]{self._footer()}[/dim]")
                break

    def _footer(self) -> str:
        """Status line under each answer: model, working directory, git branch, and context usage."""
        cwd = Path.cwd()
        home = str(Path.home())
        path = str(cwd)
        if path == home or path.startswith(home + os.sep):
            path = "~" + path[len(home):]
        branch = _git_branch(cwd)
        where = f"{escape(path)} ({escape(branch)})" if branch else escape(path)

        if self.model_limit:
            percent = (self.prompt_token_count / self.model_limit) * 100
            ctx = f"ctx {self.prompt_token_count:,} / {self.model_limit:,} ({percent:.1f}%)"
        else:
            ctx = f"ctx {self.prompt_token_count:,}"
        return f"{where} | {escape(self.model)} | {ctx}"
