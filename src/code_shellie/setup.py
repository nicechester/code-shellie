import getpass

from .config import save_config, get_api_key
from .term import bold, green

def _ask(label: str, default: str, secret: bool = False) -> str:
    """Prompt for a value. Empty input keeps the default. Secrets are not echoed."""
    shown = (f"...{default[-4:]}" if len(default) > 4 else "set") if secret and default else default
    prompt = f"{label}" + (f" [{shown}]" if default else "") + ": "
    answer = getpass.getpass(prompt) if secret else input(prompt)
    return answer.strip() or default

def run_setup():
    print(bold("=== Code Shellie Setup ==="))
    print("Please configure your Gemini API credentials.\n")

    api_key = _ask("Gemini API Key", get_api_key(), secret=True)
    model_name = _ask("Gemini Model Name", "gemini-3.5-flash-lite")

    save_config(api_key, model_name)
    print(green("Configuration saved successfully to ~/.config/codesh/.env!") + "\n")
