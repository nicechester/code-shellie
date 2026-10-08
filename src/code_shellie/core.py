import os
import re
import time
from google import genai
from google.genai import errors, types
from rich.console import Console
from .config import get_api_key, get_model_name
from .tools import TOOL_DECLARATIONS, execute_tool
from .context import load_contexts
from .mentions import expand_mentions
from .mcp_client import get_manager

console = Console()

DEFAULT_RPM_COOLDOWN = 60
_5XX_BACKOFF_SEC = (1, 2, 4)

def _retry_delay(error) -> int:
    """Seconds to wait from the API's retry hint, with a 1s margin."""
    match = re.search(r"retry(?:Delay': '| in )(\d+(?:\.\d+)?)s", str(error))
    return int(float(match.group(1))) + 1 if match else DEFAULT_RPM_COOLDOWN

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

    def _send(self, message):
        """Send a message, following the policy in shellie/docs/gemini_429_observations.md.

        RPM: sleep the server's retryDelay, retry once, then give up.
        RPD: give up (no fallback model here).
        5xx: retry with exponential backoff (1s, 2s, 4s), then give up.
        """
        rpm_retried = False
        server_retries = 0
        while True:
            try:
                return self.chat.send_message(message)
            except errors.APIError as e:
                if e.code == 429:
                    if "PerDay" in str(e):
                        console.print("[bold red]Daily quota (RPD) reached. Stopping.[/bold red]")
                        raise
                    if rpm_retried:
                        console.print("[bold red]Per-minute quota hit again after cooldown. Stopping.[/bold red]")
                        raise
                    rpm_retried = True
                    delay = _retry_delay(e)
                    console.print(f"[yellow]Rate limit (RPM) hit. Cooling down for {delay}s, then retrying once...[/yellow]")
                    time.sleep(delay)
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
                for function_call in response.function_calls:
                    name = function_call.name
                    args = function_call.args
                    console.print(f"[yellow]⚡ Executing tool: {name}({args})[/yellow]")
                    
                    # Execute tool
                    result = execute_tool(name, args)
                    console.print(f"[dim]Result: {str(result)[:200]}...[/dim]")
                    
                    # Send tool output back to chat
                    response = self._send(
                        types.Part.from_function_response(
                            name=name,
                            response={"result": result}
                        )
                    )
            else:
                if response.text:
                    console.print(f"\n[bold green]Code Shellie:[/bold green]\n{response.text}\n")
                break
