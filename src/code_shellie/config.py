import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "shellie-code"
ENV_PATH = CONFIG_DIR / ".env"


def parse_dotenv(path) -> dict:
    """Parse a .env file into a dict without touching os.environ. Missing file -> {}."""
    result = {}
    path = Path(path)
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        result[key.strip()] = value
    return result


def load_environment():
    """Load the saved config, then a .env in the working directory. Existing environment variables win."""
    for path in (ENV_PATH, Path.cwd() / ".env"):
        for key, value in parse_dotenv(path).items():
            os.environ.setdefault(key, value)


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
    return os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
