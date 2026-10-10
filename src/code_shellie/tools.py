from pathlib import Path

from .config import get_api_key, get_search_model
from .gemini import search as gemini_search
from .mcp_client import get_manager
from .memory import remember as remember_lesson
from .shell import run_command

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
    return run_command(command)

def execute_web_search(query: str) -> str:
    """Look up current information with Google Search grounding, using the SEARCH_MODEL setting."""
    return gemini_search(query, get_search_model(), get_api_key())

# Tool implementations registry
TOOL_FUNCTIONS = {
    "read_file": read_file,
    "write_file": write_file,
    "list_directory": list_directory,
    "run_shell_command": run_shell_command,
    "execute_web_search": execute_web_search,
    "remember": remember_lesson,
}

# Gemini function declarations as plain dicts (REST field names, OpenAPI-style schema)
TOOL_DECLARATIONS = [
    {
        "name": "read_file",
        "description": "Read and return the text contents of a file.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "file_path": {"type": "STRING", "description": "Path of the file to read."},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write text content to a file (creates parent directories if needed).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "file_path": {"type": "STRING", "description": "Path of the file to write."},
                "content": {"type": "STRING", "description": "The text content to write into the file."},
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files and directories in a given path (ignores hidden files).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "dir_path": {
                    "type": "STRING",
                    "description": "Directory path to list (defaults to current directory '.' if omitted).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "run_shell_command",
        "description": "Execute a bash shell command and return output.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command": {"type": "STRING", "description": "The shell command to execute."},
            },
            "required": ["command"],
        },
    },
    {
        "name": "execute_web_search",
        "description": "Search the web for current information using Google Search grounding.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "remember",
        "description": (
            "Save one confirmed, non-obvious project lesson to .shellie/MEMORY.md. "
            "Saved lessons are added to the system prompt in later sessions."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "fact": {"type": "STRING", "description": "One short line stating the lesson."},
            },
            "required": ["fact"],
        },
    },
]

def all_declarations() -> list:
    """Built-in declarations plus the tools of connected MCP servers."""
    return [*TOOL_DECLARATIONS, *get_manager().declarations()]

def execute_tool(name: str, args: dict) -> str:
    manager = get_manager()
    if manager.has_tool(name):
        return manager.call(name, args)
    if name not in TOOL_FUNCTIONS:
        return f"Error: Tool '{name}' not found."
    try:
        return TOOL_FUNCTIONS[name](**args)
    except Exception as e:
        return f"Error executing tool '{name}': {e}"
