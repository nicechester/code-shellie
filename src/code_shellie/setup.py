import click
from rich.console import Console
from .config import save_config, get_api_key

console = Console()

def run_setup():
    console.print("[bold cyan]=== Code Shellie Setup ===[/bold cyan]")
    console.print("Please configure your Gemini API credentials.\n")
    
    current_key = get_api_key()
    masked_key = f"...{current_key[-4:]}" if len(current_key) > 4 else "Not Set"
    
    api_key = click.prompt("Gemini API Key", default=current_key, hide_input=True)
    model_name = click.prompt("Gemini Model Name", default="gemini-2.5-flash")
    
    save_config(api_key, model_name)
    console.print("[bold green]Configuration saved successfully to ~/.config/shellie-code/.env![/bold green]\n")
