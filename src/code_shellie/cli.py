import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import CONFIG_DIR, get_api_key, get_model_name, save_model
from . import __version__, sessions
from .setup import run_setup
from .core import KEEP_TURNS, Agent
from .clipboard import copy_to_clipboard
from .completion import complete
from . import gemini
from .gemini import GeminiError
from .line_editor import LineEditor
from .mcp_client import get_manager, shutdown_mcp
from .skills import disable_skill, enable_skill, enabled_skills, list_skills, skill_instructions, skill_request
from .term import bold, cyan, dim, green, red, yellow

CLEAR_SCREEN = "\x1b[2J\x1b[H"
LATEST = "latest"  # --resume without an id: the latest session for this directory
UPDATE_INSTALLER_URL = "https://raw.githubusercontent.com/nicechester/code-shellie/main/install.sh"


def parse_update_command(command):
    """Return the requested ref for /update, or None when command is not /update."""
    parts = command.split()
    if not parts or parts[0] != "/update":
        return None
    if len(parts) > 2:
        raise ValueError("Usage: /update [ref]")
    return parts[1] if len(parts) == 2 else "main"


def _installed_version():
    try:
        result = subprocess.run(
            [sys.executable, "-c", "from importlib.metadata import version; print(version('code-shellie'))"],
            check=False, capture_output=True, text=True,
        )
    except OSError:
        return "unknown"
    return (result.stdout.strip() or "unknown") if result.returncode == 0 else "unknown"


def _find_checkout_root():
    """Find the source checkout when this install imports code directly from a Git worktree."""
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() and (parent / "pyproject.toml").is_file():
            return parent
    return None


def _update_checkout(root, ref):
    """Fast-forward the cloned installation and refresh its editable package metadata."""
    def git(*args):
        return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, check=False)

    try:
        status = git("status", "--porcelain")
        if status.returncode != 0:
            print(red(f"Update failed: could not inspect the checkout: {status.stderr.strip()}"))
            return False
        if status.stdout.strip():
            print(red("Update failed: the cloned install has local changes. Commit or stash them before updating."))
            return False

        branch = git("symbolic-ref", "--quiet", "--short", "HEAD")
        if branch.returncode != 0:
            print(red("Update failed: the cloned install is on a detached HEAD. Switch to a branch and retry."))
            return False
        upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
        if upstream.returncode != 0:
            print(red("Update failed: the current branch has no upstream. Set one with git branch --set-upstream-to."))
            return False

        pull_args = ["pull", "--ff-only"]
        if ref != "main":
            remote = upstream.stdout.strip().split("/", 1)[0]
            pull_args.extend([remote, ref])
        pull = git(*pull_args)
        if pull.returncode != 0:
            print(red(f"Update failed: git pull could not fast-forward this checkout: {pull.stderr.strip()}"))
            return False

        refresh = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-deps", "--no-build-isolation", "-e", str(root)],
            cwd=str(root), capture_output=True, text=True, check=False,
        )
        if refresh.returncode != 0:
            print(red("The source was pulled, but refreshing the editable install failed."))
            if refresh.stderr.strip():
                print(dim(refresh.stderr.strip()))
            return False
    except OSError as e:
        print(red(f"Update failed: {e}"))
        return False
    return True


def run_update(ref="main"):
    """Update a cloned checkout directly, or use install.sh for an archive-based install."""
    old_version = __version__
    print(f"Updating Code Shellie from {old_version} to {ref}...")
    env = os.environ.copy()
    env["CODESH_REF"] = ref

    checkout = _find_checkout_root()
    if checkout is not None:
        if not _update_checkout(checkout, ref):
            return False
    else:
        try:
            with tempfile.TemporaryDirectory(prefix="codesh-update-") as temp_dir:
                installer = Path(temp_dir) / "install.sh"
                download = subprocess.run(
                    ["curl", "-fsSL", UPDATE_INSTALLER_URL, "-o", str(installer)], check=False,
                )
                if download.returncode != 0:
                    print(red("Update failed: could not download the installer. The installed copy was not changed."))
                    return False
                install = subprocess.run(["bash", str(installer)], env=env, check=False)
                if install.returncode != 0:
                    print(red("Update failed. The existing installation was restored if replacement had started."))
                    return False
        except OSError as e:
            print(red(f"Update failed: {e}. The installed copy was not changed."))
            return False

    new_version = _installed_version()
    print(green(f"Updated Code Shellie: {old_version} -> {new_version}"))
    print(yellow("Restart codesh to load the new version."))
    return True


def _print_skills():
    skills = list_skills()
    if not skills:
        print("No skills installed. Add one at ~/.config/codesh/skills/<name>/SKILL.md.")
        return
    enabled = set(enabled_skills())
    print(yellow("Skills:"))
    for name, description in skills.items():
        state = green("on ") if name in enabled else dim("off")
        print(f"  {state} {cyan('/' + name)} - {description}")


def _one_line(text: str, limit: int) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[:limit - 3] + "..."


def print_sessions():
    rows = sessions.list_sessions()
    if not rows:
        print("No saved sessions.")
        return
    for data in rows:
        if "history" not in data:
            print(f"{data['id']}  {red(data['description'])}")
            continue
        print(f"{data['id']}  {sessions.format_time(data['updated'])}  {dim(data['cwd'])}  {data['description']}")


def print_exit_hint(agent):
    if agent.session is not None:
        print(dim(f"Resume this session with: codesh --resume {agent.session['id']}"))


def resume_session(agent, which):
    """Load a saved session into agent. Exits with a message if it cannot be loaded."""
    try:
        if which == LATEST:
            data = sessions.latest_for_directory(os.getcwd())
            if data is None:
                raise sessions.SessionError("No saved session for this directory. See codesh --sessions.")
        else:
            data = sessions.load(which)
    except sessions.SessionError as e:
        print(red(str(e)))
        sys.exit(1)
    agent.restore(data)
    print(bold(f"Resumed session {data['id']}: {data['description']}"))
    if data.get("cwd") != os.getcwd():
        print(yellow(f"Note: this session was started in {data.get('cwd')}. File paths in it may not apply here."))
    for prompt_text, answer in sessions.recent_turns(data["history"]):
        print(dim(f"> {_one_line(prompt_text, 100)}"))
        print(f"  {_one_line(answer, 200)}")
    print()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Code Shellie: Your AI Coding Agent")
    parser.add_argument("--version", action="version", version=f"codesh {__version__}")
    parser.add_argument("prompt", nargs="?", help="run one request and exit; omit for the interactive REPL")
    parser.add_argument("--resume", nargs="?", const=LATEST, default=None, metavar="ID",
                        help="continue a saved session: the latest for this directory, or the one with ID")
    parser.add_argument("--sessions", action="store_true", help="list saved sessions and exit")
    parser.add_argument("--update", nargs="?", const="main", default=None, metavar="REF",
                        help="update Code Shellie from main or the given tag/commit")
    args = parser.parse_args(argv)
    if args.update is not None:
        try:
            if not run_update(args.update):
                sys.exit(1)
        finally:
            shutdown_mcp()
        return
    if args.sessions:
        print_sessions()
        return
    try:
        run(args.prompt, args.resume)
    finally:
        # Forget MCP connections before the interpreter exits
        shutdown_mcp()


def run(prompt, resume=None):
    if prompt:
        try:
            update_ref = parse_update_command(prompt)
        except ValueError as e:
            print(red(str(e)))
            return
        if update_ref is not None:
            if not run_update(update_ref):
                sys.exit(1)
            return

    sessions.purge_expired()
    api_key = get_api_key()
    if not api_key:
        print(yellow("No API key found. Entering setup mode..."))
        run_setup()

    try:
        agent = Agent()
    except Exception as e:
        print(red(f"Error initializing agent: {e}"))
        print("Run " + bold("codesh /setup") + " to reconfigure.")
        sys.exit(1)

    if resume is not None:
        resume_session(agent, resume)

    if prompt:
        if prompt == "/setup":
            run_setup()
            return
        if prompt == "/clear":
            print(CLEAR_SCREEN, end="")
            return
        if prompt == "/reset":
            agent.discard_session()
            print(green("Conversation history reset. The saved session was deleted."))
            return
        if prompt.startswith("!"):
            # Execute shell command directly
            cmd = prompt[1:].strip()
            print(cyan(f"Running shell: {cmd}"))
            subprocess.run(cmd, shell=True)
            return
        if prompt.startswith("/"):
            print(red(f"no such command: {prompt.split()[0]}"))
            return

        try:
            agent.run_turn(prompt)
        except GeminiError as e:
            print(red(f"Request failed: {e.message}"))
        print_exit_hint(agent)
        return

    # Interactive REPL mode
    print(bold(cyan(f"Welcome to Code Shellie {__version__} (Interactive REPL)")))
    print("Type your instructions, '!command' to run shell, '/setup' to reconfigure, or 'exit'/'/exit' to quit.")
    print("Enter submits; Alt+Enter or Ctrl+J adds a newline. Pasted multi-line text stays in one prompt.")
    print("Tab completes commands and @paths. Output is compact by default; Ctrl+O switches to verbose (tool arguments and results).\n")

    def toggle_view():
        # Class-level, so the view survives /model, /setup and skill changes that re-create the agent
        Agent.verbose = not Agent.verbose
        return "verbose" if Agent.verbose else "compact"

    editor = LineEditor(completer=complete, on_toggle_view=toggle_view, history_path=CONFIG_DIR / "history.jsonl")
    while True:
        try:
            user_input = editor.read().strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "/exit", "/quit"):
                break
            if user_input == "/help":
                print(yellow("Available Commands:"))
                print(f"  {cyan('/help')}    - Show this help message")
                print(f"  {cyan('/setup')}   - Reconfigure Gemini API credentials and model")
                print(f"  {cyan('/model')}   - Show or change the Gemini model (/model <name>)")
                print(f"  {cyan('/mcp')}     - Show configured MCP servers and their tools")
                print(f"  {cyan('/context')} - Show current context usage")
                print(f"  {cyan('/clear')}   - Clear the terminal screen")
                print(f"  {cyan('/reset')}   - Reset conversation history / chat session")
                print(f"  {cyan('/compress')} - Summarize older turns to free context space (keeps the last {KEEP_TURNS})")
                print(f"  {cyan('/copy')}    - Copy the last answer to the clipboard")
                print(f"  {cyan('/sessions')} - List saved sessions")
                print(f"  {cyan('/update [ref]')} - Update Code Shellie from main or a tag/commit")
                print(f"  {cyan('/sources')} - Show the full URLs of the last web search's sources")
                print(f"  {cyan('/diff')}    - Show the diffs of files edited in the last turn")
                print(f"  {cyan('/skills')}  - List skills and whether each is enabled")
                print(f"  {cyan('/skill enable|disable <name>')} - Turn a skill on or off")
                print(f"  {cyan('/<skill>')} - Enable a skill by name")
                print(f"  {cyan('Ctrl+O')}   - Switch between compact and verbose output")
                print(f"  {cyan('!command')} - Run a shell command directly")
                print(f"  {cyan('@path')}    - Attach a file or directory listing to your message")
                print(f"  {cyan('exit/quit, /exit, /quit')} - Exit the REPL")
                continue
            try:
                update_ref = parse_update_command(user_input)
            except ValueError as e:
                print(red(str(e)))
                continue
            if update_ref is not None:
                run_update(update_ref)
                continue
            if user_input == "/mcp":
                get_manager().print_status()
                continue
            if user_input == "/context":
                print(f"Context: {agent.prompt_token_count:,} / {agent.model_limit or 0:,} tokens")
                print(f"Session total: {agent.total_token_count:,} tokens")
                print(f"Session API requests: {agent.total_api_requests:,}")
                continue
            if user_input == "/clear":
                print(CLEAR_SCREEN, end="")
                continue
            if user_input == "/reset":
                agent.discard_session()
                print(green("Conversation history reset. The saved session was deleted."))
                continue
            if user_input == "/compress":
                try:
                    turns = agent.compress()
                except KeyboardInterrupt:
                    print(yellow("\nStopped. The conversation is unchanged."))
                    continue
                except Exception as e:
                    print(red(f"Could not compress: {getattr(e, 'message', None) or e}"))
                    continue
                if turns == 0:
                    print(yellow(f"Nothing to compress: the chat has {KEEP_TURNS} turns or fewer."))
                else:
                    print(green(f"Summarized {turns} older turn(s). The last {KEEP_TURNS} are kept as they were."))
                    print(dim(f"Context now {agent.prompt_token_count:,} / {agent.model_limit or 0:,} tokens."))
                continue
            if user_input == "/sessions":
                print_sessions()
                continue
            if user_input == "/sources":
                if not gemini.last_sources:
                    print(yellow("No sources yet. Run a web search first."))
                for i, (title, uri) in enumerate(gemini.last_sources, 1):
                    print(f"[{i}] {title} - {gemini.resolve_url(uri)}")
                continue
            if user_input == "/diff":
                if not agent.last_edits:
                    print(yellow("No files were edited in the last turn."))
                    continue
                diff = agent.edits_diff()
                if not diff:
                    print(yellow("The files edited in the last turn have no net changes."))
                    continue
                for line in diff.splitlines():
                    if line.startswith(("+++", "---")):
                        print(dim(line))
                    elif line.startswith("+"):
                        print(green(line))
                    elif line.startswith("-"):
                        print(red(line))
                    else:
                        print(line)
                continue
            if user_input == "/copy":
                if not agent.last_answer:
                    print(yellow("No answer to copy yet."))
                elif tool := copy_to_clipboard(agent.last_answer):
                    print(green(f"Copied the last answer to the clipboard ({tool})."))
                else:
                    print(red("No clipboard tool found. Install wl-clipboard, xclip, or xsel."))
                continue
            if user_input == "/setup":
                run_setup()
                agent = Agent()  # re-init
                continue
            if user_input == "/model" or user_input.startswith("/model "):
                name = user_input[len("/model"):].strip()
                if not name:
                    print(f"Current model: {bold(get_model_name())}")
                    print("Usage: /model <name>, e.g. /model gemini-2.5-pro")
                    continue
                save_model(name)
                agent = Agent()  # re-init so the new model takes effect
                print(f"Model set to {bold(name)} (saved). Conversation history was reset.")
                continue
            if user_input == "/skills":
                _print_skills()
                continue
            if user_input == "/skill" or user_input.startswith("/skill "):
                parts = user_input.split()
                if len(parts) != 3 or parts[1] not in ("enable", "disable"):
                    print("Usage: /skill enable <name> or /skill disable <name>. See /skills.")
                    continue
                action, name = parts[1], parts[2]
                if action == "enable":
                    if not enable_skill(name):
                        print(red(f"No skill named {name}. See /skills."))
                        continue
                    agent.refresh_skills()
                    print(f"Skill {cyan('/' + name)} enabled. Conversation history was reset.")
                else:
                    if not disable_skill(name):
                        print(f"Skill {cyan('/' + name)} is not enabled.")
                        continue
                    agent.refresh_skills()
                    print(f"Skill {cyan('/' + name)} disabled. Conversation history was reset.")
                continue
            if user_input.startswith("!"):
                cmd = user_input[1:].strip()
                try:
                    subprocess.run(cmd, shell=True)
                except KeyboardInterrupt:
                    # Ctrl+C stops the command, not codesh; the shell has already received the signal too
                    print()
                continue
            skill_name, _, skill_args = user_input[1:].partition(" ")
            label = None
            if user_input.startswith("/") and skill_name in list_skills():
                # Typing /<skill> [args] enables the skill if needed, then runs it as this turn's request
                if skill_name not in enabled_skills():
                    enable_skill(skill_name)
                    agent.refresh_skills()
                    print(f"Skill {cyan('/' + skill_name)} enabled. Conversation history was reset.")
                instructions = skill_instructions(skill_name)
                if instructions is None:
                    print(red(f"Cannot read skill {skill_name}. See /skills."))
                    continue
                label = user_input
                user_input = skill_request(skill_name, instructions, skill_args)
            if user_input.startswith("/"):
                print(red(f"no such command: {user_input.split()[0]}"))
                continue

            try:
                agent.run_turn(user_input, label=label)
            except KeyboardInterrupt:
                # Ctrl+C stops this request only; run_turn has already dropped it from the history
                print(yellow("\nStopped. The request was dropped; the conversation is unchanged."))
            except Exception as e:
                # Keep the session and its history; the user can retry the prompt
                print(red(f"Request failed: {getattr(e, 'message', None) or e}"))
        except (KeyboardInterrupt, EOFError):
            print(cyan("\nGoodbye!"))
            break
    print_exit_hint(agent)


if __name__ == "__main__":
    main()
