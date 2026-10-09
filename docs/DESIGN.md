# Code Shellie — Architectural Design Document

## 1. Overview
`codesh` is an autonomous, Gemini-powered coding agent inspired by Claude Code. It runs primarily in the developer's local terminal (CLI) and supports interactive approval prompts. By leveraging Gemini's massive context window, it can ingest entire codebases, reason about complex refactoring and bug fixing, and execute tools securely on the host machine.

---

## 2. Core Architecture & Project Structure
Standard Python project layout located at `~/src/shellie-code`:

```
shellie-code/
├── pyproject.toml
├── README.md
├── DESIGN.md
├── src/
│   └── code_shellie/
│       ├── __init__.py
│       ├── core.py       # Gemini Agent Loop & Tool execution engine
│       ├── tools.py      # File I/O, Shell execution, Git operations
│       └── cli.py        # Terminal interface (stdlib line editor)
└── tests/
    ├── __init__.py
    └── test_core.py
```

---

## 3. Component Details

### 3.1 `tools.py` (Tool Definitions)
The agent interacts with the filesystem and OS via defined function calling tools:
- `read_file(path: str)`: Reads file contents with line numbers.
- `write_file(path: str, content: str)`: Creates or overwrites files.
- `edit_file(path: str, old_str: str, new_str: str)`: Performs precise string replacements.
- `run_shell(command: str)`: Executes safe shell commands (e.g., `pytest`, `npm test`, `git status`).
- `git_diff()`: Returns unstaged and staged git changes.

### 3.2 `core.py` (Agent Loop)
- Manages conversation history and state.
- Sends prompts and conversation history to the Gemini REST API (`urllib`, no SDK).
- Handles `FUNCTION_CALL` responses, executing the requested tool via `tools.py`, and feeding results back to Gemini.
- Supports an **Approval Hook** before executing destructive tools (like `write_file` or `run_shell`).

### 3.3 `cli.py` (Terminal Interface)
- Standard library only: `argparse` for flags, `termios` for the line editor, plain ANSI colors.
- Provides streaming output, syntax highlighting, and interactive prompts (`[Y/n]` confirmations).

---

## 4. Execution Flow
1. User invokes `codesh "Fix the bug in main.py"` in the terminal.
2. `core.py` initializes context (including git status and directory structure) and queries Gemini.
3. Gemini decides to call `read_file("src/main.py")`.
4. `cli.py` displays the planned tool call and asks for confirmation if required.
5. Tool executes, output is returned to Gemini.
6. Gemini synthesizes the final response or iterates.
