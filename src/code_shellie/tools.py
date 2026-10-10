import os
import re
from pathlib import Path

from .config import get_api_key, get_search_model
from .gemini import search as gemini_search
from .mcp_client import get_manager
from .memory import remember as remember_lesson
from .shell import run_command

SEARCH_MATCH_LIMIT = 50  # matches returned per pattern, so one broad pattern cannot flood the context
MAX_LIST_DEPTH = 5
SKIPPED_DIRS = {"__pycache__", "node_modules", "venv"}

def _read_one(file_path: str, start_line=None, end_line=None) -> str:
    path = Path(file_path).expanduser()
    if not path.exists():
        return f"Error: File '{file_path}' does not exist."
    text = path.read_text(encoding="utf-8")
    if start_line is None and end_line is None:
        return text
    lines = text.splitlines()
    first = max(int(start_line or 1), 1)
    last = min(int(end_line or len(lines)), len(lines))
    return "\n".join(lines[first - 1:last])

def read_file(file_path: str = None, start_line: int = None, end_line: int = None, files: list = None) -> str:
    """Read one file, or a line range of it. `files` reads several files in one call, each with its own optional range."""
    try:
        requests = list(files or [])
        if file_path:
            requests.insert(0, {"file_path": file_path, "start_line": start_line, "end_line": end_line})
        if not requests:
            return "Error: give file_path or files."
        if len(requests) == 1 and not files:
            return _read_one(file_path, start_line, end_line)
        sections = []
        for request in requests:
            path = request.get("file_path", "")
            start, end = request.get("start_line"), request.get("end_line")
            label = f"=== {path}" + (f" (lines {start or 1}-{end or 'end'})" if start or end else "") + " ==="
            try:
                body = _read_one(path, start, end)
            except Exception as e:
                body = f"Error reading file: {e}"
            sections.append(f"{label}\n{body}")
        return "\n\n".join(sections)
    except Exception as e:
        return f"Error reading file: {e}"

def search_files(patterns: list, path: str = ".") -> str:
    """Search files under path for each regular expression in patterns. Returns file:line matches, one group per pattern."""
    try:
        root = Path(path).expanduser()
        if not root.exists():
            return f"Error: Path '{path}' does not exist."
        compiled = []
        for pattern in patterns:
            try:
                compiled.append((pattern, re.compile(pattern)))
            except re.error as e:
                return f"Error: invalid pattern '{pattern}': {e}"
        matches = {pattern: [] for pattern, _ in compiled}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIPPED_DIRS]
            for filename in sorted(filenames):
                if filename.startswith("."):
                    continue
                file = Path(dirpath) / filename
                try:
                    lines = file.read_text(encoding="utf-8").splitlines()
                except (UnicodeDecodeError, OSError):
                    continue  # binary or unreadable files cannot match a text search
                for number, line in enumerate(lines, start=1):
                    for pattern, regex in compiled:
                        if len(matches[pattern]) < SEARCH_MATCH_LIMIT and regex.search(line):
                            matches[pattern].append(f"{file}:{number}: {line.strip()}")
        sections = []
        for pattern, _ in compiled:
            found = list(matches[pattern]) or ["(no matches)"]
            header = f"=== {pattern} ({len(matches[pattern])} matches) ==="
            if len(matches[pattern]) == SEARCH_MATCH_LIMIT:
                found.append("(limit reached; narrow the pattern or path)")
            sections.append("\n".join([header, *found]))
        return "\n\n".join(sections)
    except Exception as e:
        return f"Error searching files: {e}"

def write_file(file_path: str, content: str) -> str:
    """Write contents to a file."""
    try:
        path = Path(file_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Successfully wrote to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"

def list_directory(dir_path: str = ".", depth: int = 1) -> str:
    """List files and directories in a given path, down to `depth` levels (1 lists only the directory itself)."""
    try:
        path = Path(dir_path).expanduser()
        if not path.exists():
            return f"Error: Directory '{dir_path}' does not exist."
        depth = min(max(int(depth or 1), 1), MAX_LIST_DEPTH)
        result = []

        def walk(directory: Path, level: int):
            items = sorted(directory.iterdir(), key=lambda x: (not x.is_dir(), x.name))
            for item in items:
                if item.name.startswith('.'):
                    continue
                item_type = "📁" if item.is_dir() else "📄"
                result.append("  " * (level - 1) + f"{item_type} {item.name}")
                if item.is_dir() and level < depth and item.name not in SKIPPED_DIRS:
                    walk(item, level + 1)

        walk(path, 1)
        return "\n".join(result)
    except Exception as e:
        return f"Error listing directory: {e}"

def run_shell_command(command: str = None, commands: list = None) -> str:
    """Run one shell command, or several in one call (`commands`). Each result is labeled with its command."""
    if not commands:
        if not command:
            return "Error: give command or commands."
        return run_command(command)
    sections = []
    for item in commands:
        sections.append(f"$ {item}\n{run_command(item)}")
    return "\n\n".join(sections)

def execute_web_search(query: str) -> str:
    """Look up current information with Google Search grounding, using the SEARCH_MODEL setting."""
    return gemini_search(query, get_search_model(), get_api_key())

# Tool implementations registry
TOOL_FUNCTIONS = {
    "read_file": read_file,
    "write_file": write_file,
    "list_directory": list_directory,
    "search_files": search_files,
    "run_shell_command": run_shell_command,
    "execute_web_search": execute_web_search,
    "remember": remember_lesson,
}

# Gemini function declarations as plain dicts (REST field names, OpenAPI-style schema)
TOOL_DECLARATIONS = [
    {
        "name": "read_file",
        "description": (
            "Read and return the text contents of a file. Use start_line and end_line to read a range (1-based, inclusive). "
            "Use files to read several files in one call, each with its own optional range."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "file_path": {"type": "STRING", "description": "Path of the file to read."},
                "start_line": {"type": "INTEGER", "description": "First line to return (default 1)."},
                "end_line": {"type": "INTEGER", "description": "Last line to return (default: end of file)."},
                "files": {
                    "type": "ARRAY",
                    "description": "Several files to read in one call.",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "file_path": {"type": "STRING"},
                            "start_line": {"type": "INTEGER"},
                            "end_line": {"type": "INTEGER"},
                        },
                        "required": ["file_path"],
                    },
                },
            },
            "required": [],
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
        "description": "List files and directories in a given path, optionally several levels deep (ignores hidden files).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "dir_path": {
                    "type": "STRING",
                    "description": "Directory path to list (defaults to current directory '.' if omitted).",
                },
                "depth": {
                    "type": "INTEGER",
                    "description": "How many levels to list (default 1, the directory's own entries only; max 5).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_files",
        "description": (
            "Search file contents under a path for regular expressions, in one call. Returns file:line matches "
            "for each pattern. Hidden, binary and dependency directories are skipped."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "patterns": {
                    "type": "ARRAY",
                    "description": "Regular expressions to search for. Several patterns are searched in one pass.",
                    "items": {"type": "STRING"},
                },
                "path": {"type": "STRING", "description": "Directory or file to search (default '.')."},
            },
            "required": ["patterns"],
        },
    },
    {
        "name": "run_shell_command",
        "description": (
            "Execute bash shell commands and return output. Use commands to run several independent commands "
            "in one call; each result is labeled with its command."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command": {"type": "STRING", "description": "A single shell command to execute."},
                "commands": {
                    "type": "ARRAY",
                    "description": "Several shell commands to execute in one call, in order.",
                    "items": {"type": "STRING"},
                },
            },
            "required": [],
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
