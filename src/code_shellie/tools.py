from google.genai import types
import os
import subprocess
from pathlib import Path

from .mcp_client import get_manager

def read_file(file_path: str) -> str:
    """Read contents of a file."""
    try:
        path = Path(file_path).expanduser()
        if not path.exists():
            return f"Error: File '{file_path}' does not exist."
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

def write_file(file_path: str, content: str) -> str:
    """Write contents to a file."""
    try:
        path = Path(file_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Successfully wrote to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"

def list_directory(dir_path: str = ".") -> str:
    """List files and directories in a given path."""
    try:
        path = Path(dir_path).expanduser()
        if not path.exists():
            return f"Error: Directory '{dir_path}' does not exist."
        items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
        result = []
        for item in items:
            if item.name.startswith('.'):
                continue
            item_type = "📁" if item.is_dir() else "📄"
            result.append(f"{item_type} {item.name}")
        return "\n".join(result)
    except Exception as e:
        return f"Error listing directory: {e}"

def run_shell_command(command: str) -> str:
    """Run a shell command and return its output."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[Exit code: {result.returncode}]"
        return output.strip() if output.strip() else "[Command executed with no output]"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 60 seconds."
    except Exception as e:
        return f"Error executing command: {e}"

# Tool implementations registry
TOOL_FUNCTIONS = {
    "read_file": read_file,
    "write_file": write_file,
    "list_directory": list_directory,
    "run_shell_command": run_shell_command,
}

# Gemini Function Declarations using google.genai.types
GEMINI_TOOLS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="read_file",
            description="Read and return the text contents of a file.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "file_path": types.Schema(
                        type=types.Type.STRING,
                        description="Path of the file to read."
                    )
                },
                required=["file_path"],
            ),
        ),
        types.FunctionDeclaration(
            name="write_file",
            description="Write text content to a file (creates parent directories if needed).",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "file_path": types.Schema(
                        type=types.Type.STRING,
                        description="Path of the file to write."
                    ),
                    "content": types.Schema(
                        type=types.Type.STRING,
                        description="The text content to write into the file."
                    ),
                },
                required=["file_path", "content"],
            ),
        ),
        types.FunctionDeclaration(
            name="list_directory",
            description="List files and directories in a given path (ignores hidden files).",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "dir_path": types.Schema(
                        type=types.Type.STRING,
                        description="Directory path to list (defaults to current directory '.' if omitted)."
                    )
                },
                required=[],
            ),
        ),
        types.FunctionDeclaration(
            name="run_shell_command",
            description="Execute a bash shell command and return output.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "command": types.Schema(
                        type=types.Type.STRING,
                        description="The shell command to execute."
                    )
                },
                required=["command"],
            ),
        ),
    ]
)

# Compatibility aliases for core.py
TOOL_DECLARATIONS = GEMINI_TOOLS
TOOL_MAP = TOOL_FUNCTIONS

def execute_tool(name: str, args: dict) -> str:
    manager = get_manager()
    if manager.has_tool(name):
        return manager.call(name, args)
    if name not in TOOL_MAP:
        return f"Error: Tool '{name}' not found."
    try:
        return TOOL_MAP[name](**args)
    except Exception as e:
        return f"Error executing tool '{name}': {e}"
