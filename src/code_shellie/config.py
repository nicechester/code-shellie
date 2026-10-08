import os
from pathlib import Path
from dotenv import load_dotenv

CONFIG_DIR = Path.home() / ".config" / "shellie-code"
ENV_PATH = CONFIG_DIR / ".env"

def load_environment():
    """Load environment variables from user config or working directory."""
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
    load_dotenv() # also check local .env

def save_config(api_key: str, model_name: str):
    """Save configuration to ~/.config/shellie-code/.env"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(ENV_PATH, "w") as f:
        f.write(f"GEMINI_API_KEY={api_key}\n")
        f.write(f"GEMINI_MODEL={model_name}\n")
    # Also reload into current environment
    os.environ["GEMINI_API_KEY"] = api_key
    os.environ["GEMINI_MODEL"] = model_name

def save_model(model_name: str):
    """Update GEMINI_MODEL in ~/.config/shellie-code/.env, keeping the other settings."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    lines = [line for line in lines if not line.startswith("GEMINI_MODEL=")]
    lines.append(f"GEMINI_MODEL={model_name}")
    ENV_PATH.write_text("\n".join(lines) + "\n")
    os.environ["GEMINI_MODEL"] = model_name

def get_api_key() -> str:
    load_environment()
    return os.getenv("GEMINI_API_KEY", "")

def get_model_name() -> str:
    load_environment()
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
