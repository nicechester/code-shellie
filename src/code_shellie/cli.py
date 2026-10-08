import os
import subprocess
import sys
import click
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import merge_completers
from prompt_toolkit.formatted_text import ANSI
from rich.console import Console
from .config import get_api_key, get_model_name, save_model
from .setup import run_setup
from .core import Agent
from .completion import MentionCompleter, SlashCompleter
from .mcp_client import get_manager

console = Console()

@click.command()
@click.argument("prompt", required=False)
def main(prompt):
    """Code Shellie: Your AI Coding Agent"""
    api_key = get_api_key()
    if not api_key:
        console.print("[yellow]No API key found. Entering setup mode...[/yellow]")
        run_setup()

    try:
        agent = Agent()
    except Exception as e:
        console.print(f"[bold red]Error initializing agent: {e}[/bold red]")
        console.print("Run [bold]codesh /setup[/bold] to reconfigure.")
        sys.exit(1)

    if prompt:
        if prompt == "/setup":
            run_setup()
            return
        if prompt == "/clear":
            console.clear()
            return
        if prompt == "/reset":
            agent.reset_chat()
            console.print("[green]Conversation history reset.[/green]")
            return
        if prompt.startswith("!"):
            # Execute shell command directly
            cmd = prompt[1:].strip()
            console.print(f"[cyan]Running shell: {cmd}[/cyan]")
            subprocess.run(cmd, shell=True)
            return
        if prompt.startswith("/"):
            console.print(f"[red]no such command: {prompt.split()[0]}[/red]")
            return

        agent.run_turn(prompt)
        return

    # Interactive REPL mode
    console.print("[bold cyan]Welcome to Code Shellie (Interactive REPL)[/bold cyan]")
    console.print("Type your instructions, '!command' to run shell, '/setup' to reconfigure, or 'exit'/'/exit' to quit.\n")

    completer = merge_completers([SlashCompleter(), MentionCompleter()])
    session = PromptSession(completer=completer, complete_while_typing=True)
    while True:
        try:
            user_input = session.prompt(ANSI("\x1b[1;32mcodesh>\x1b[0m ")).strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "/exit", "/quit"):
                break
            if user_input == "/help":
                console.print("[bold yellow]Available Commands:[/bold yellow]")
                console.print("  [cyan]/help[/cyan]    - Show this help message")
                console.print("  [cyan]/setup[/cyan]   - Reconfigure Gemini API credentials and model")
                console.print("  [cyan]/model[/cyan]   - Show or change the Gemini model (/model <name>)")
                console.print("  [cyan]/mcp[/cyan]     - Show configured MCP servers and their tools")
                console.print("  [cyan]/context[/cyan] - Show current context usage")
                console.print("  [cyan]/clear[/cyan]   - Clear the terminal screen")
                console.print("  [cyan]/reset[/cyan]   - Reset conversation history / chat session")
                console.print("  [cyan]!command[/cyan] - Run a shell command directly")
                console.print("  [cyan]@path[/cyan]    - Attach a file or directory listing to your message")
                console.print("  [cyan]exit/quit, /exit, /quit[/cyan] - Exit the REPL")
                continue
            if user_input == "/mcp":
                get_manager().print_status()
                continue
            if user_input == "/context":
                console.print(f"Context: {agent.prompt_token_count:,} / {agent.model_limit:,} tokens")
                console.print(f"Session total: {agent.total_token_count:,} tokens")
                continue
            if user_input == "/clear":
                console.clear()
                continue
            if user_input == "/reset":
                agent.reset_chat()
                console.print("[green]Conversation history reset.[/green]")
                continue
            if user_input == "/setup":
                run_setup()
                agent = Agent() # re-init
                continue
            if user_input == "/model" or user_input.startswith("/model "):
                name = user_input[len("/model"):].strip()
                if not name:
                    console.print(f"Current model: [bold]{get_model_name()}[/bold]")
                    console.print("Usage: /model <name>, e.g. /model gemini-2.5-pro")
                    continue
                save_model(name)
                agent = Agent() # re-init so the new model takes effect
                console.print(f"Model set to [bold]{name}[/bold] (saved). Conversation history was reset.")
                continue
            if user_input.startswith("!"):
                cmd = user_input[1:].strip()
                subprocess.run(cmd, shell=True)
                continue
            if user_input.startswith("/"):
                console.print(f"[red]no such command: {user_input.split()[0]}[/red]")
                continue

            agent.run_turn(user_input)
        except (KeyboardInterrupt, EOFError):
            console.print("\n[cyan]Goodbye![/cyan]")
            break

if __name__ == "__main__":
    main()
