import subprocess
import sys
import click
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI
from rich.console import Console
from .config import get_api_key
from .setup import run_setup
from .core import Agent
from .completion import MentionCompleter

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
        if prompt.startswith("!"):
            # Execute shell command directly
            cmd = prompt[1:].strip()
            console.print(f"[cyan]Running shell: {cmd}[/cyan]")
            subprocess.run(cmd, shell=True)
            return
            
        agent.run_turn(prompt)
        return

    # Interactive REPL mode
    console.print("[bold cyan]Welcome to Code Shellie (Interactive REPL)[/bold cyan]")
    console.print("Type your instructions, '!command' to run shell, '/setup' to reconfigure, or 'exit' to quit.\n")

    session = PromptSession(completer=MentionCompleter(), complete_while_typing=True)
    while True:
        try:
            user_input = session.prompt(ANSI("\x1b[1;32mcodesh>\x1b[0m ")).strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                break
            if user_input == "/help":
                console.print("[bold yellow]Available Commands:[/bold yellow]")
                console.print("  [cyan]/help[/cyan]    - Show this help message")
                console.print("  [cyan]/setup[/cyan]   - Reconfigure Gemini API credentials and model")
                console.print("  [cyan]!command[/cyan] - Run a shell command directly")
                console.print("  [cyan]@path[/cyan]    - Attach a file or directory listing to your message")
                console.print("  [cyan]exit/quit[/cyan]- Exit the REPL")
                continue
            if user_input == "/setup":
                run_setup()
                agent = Agent() # re-init
                continue
            if user_input.startswith("!"):
                cmd = user_input[1:].strip()
                subprocess.run(cmd, shell=True)
                continue

            agent.run_turn(user_input)
        except (KeyboardInterrupt, EOFError):
            console.print("\n[cyan]Goodbye![/cyan]")
            break

if __name__ == "__main__":
    main()
