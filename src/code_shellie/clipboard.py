import shutil
import subprocess

# Clipboard tools to try in order: macOS, Wayland, X11 (xclip, then xsel).
_CLIPBOARD_COMMANDS = (
    ["pbcopy"],
    ["wl-copy"],
    ["xclip", "-selection", "clipboard"],
    ["xsel", "--clipboard", "--input"],
)

def copy_to_clipboard(text: str) -> str | None:
    """Copy text to the system clipboard. Returns the tool used, or None if none is available."""
    for command in _CLIPBOARD_COMMANDS:
        if not shutil.which(command[0]):
            continue
        try:
            subprocess.run(command, input=text, text=True, check=True, timeout=5)
            return command[0]
        except (OSError, subprocess.SubprocessError):
            continue
    return None
