import argparse
import subprocess
import sys

from .config import get_api_key, get_model_name, save_model
from .setup import run_setup
from .core import Agent
from .clipboard import copy_to_clipboard
from .completion import complete
from .gemini import GeminiError
from .line_editor import LineEditor
from .mcp_client import get_manager, shutdown_mcp
from .skills import disable_skill, enable_skill, enabled_skills, list_skills
from .term import bold, cyan, dim, green, red, yellow

CLEAR_SCREEN = "\x1b[2J\x1b[H"


def _print_skills():
    skills = list_skills()
    if not skills:
        print("No skills installed. Add one at ~/.config/shellie-code/skills/<name>/SKILL.md.")
        return
    enabled = set(enabled_skills())
    print(yellow("Skills:"))
    for name, description in skills.items():
        state = green("on ") if name in enabled else dim("off")
        print(f"  {state} {cyan('/' + name)} - {description}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Code Shellie: Your AI Coding Agent")
    parser.add_argument("prompt", nargs="?", help="run one request and exit; omit for the interactive REPL")
    args = parser.parse_args(argv)
    try:
        run(args.prompt)
    finally:
        # Forget MCP connections before the interpreter exits
        shutdown_mcp()


def run(prompt):
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

    if prompt:
        if prompt == "/setup":
            run_setup()
            return
        if prompt == "/clear":
            print(CLEAR_SCREEN, end="")
            return
        if prompt == "/reset":
            agent.reset_chat()
            print(green("Conversation history reset."))
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
        return

    # Interactive REPL mode
    print(bold(cyan("Welcome to Code Shellie (Interactive REPL)")))
    print("Type your instructions, '!command' to run shell, '/setup' to reconfigure, or 'exit'/'/exit' to quit.")
    print("Enter submits; Alt+Enter or Ctrl+J adds a newline. Pasted multi-line text stays in one prompt.")
    print("Tab completes commands and @paths. Output is compact by default; Ctrl+O switches to verbose (tool arguments and results).\n")

    def toggle_view():
        # Class-level, so the view survives /model, /setup and skill changes that re-create the agent
        Agent.verbose = not Agent.verbose
        return "verbose" if Agent.verbose else "compact"

    editor = LineEditor(completer=complete, on_toggle_view=toggle_view)
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
                print(f"  {cyan('/copy')}    - Copy the last answer to the clipboard")
                print(f"  {cyan('/skills')}  - List skills and whether each is enabled")
                print(f"  {cyan('/skill enable|disable <name>')} - Turn a skill on or off")
                print(f"  {cyan('/<skill>')} - Enable a skill by name")
                print(f"  {cyan('Ctrl+O')}   - Switch between compact and verbose output")
                print(f"  {cyan('!command')} - Run a shell command directly")
                print(f"  {cyan('@path')}    - Attach a file or directory listing to your message")
                print(f"  {cyan('exit/quit, /exit, /quit')} - Exit the REPL")
                continue
            if user_input == "/mcp":
                get_manager().print_status()
                continue
            if user_input == "/context":
                print(f"Context: {agent.prompt_token_count:,} / {agent.model_limit or 0:,} tokens")
                print(f"Session total: {agent.total_token_count:,} tokens")
                continue
            if user_input == "/clear":
                print(CLEAR_SCREEN, end="")
                continue
            if user_input == "/reset":
                agent.reset_chat()
                print(green("Conversation history reset."))
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
                subprocess.run(cmd, shell=True)
                continue
            skill_name, _, skill_args = user_input[1:].partition(" ")
            if user_input.startswith("/") and skill_name in list_skills():
                # Typing /<skill> [args] enables the skill if needed, then runs it as this turn's request
                if skill_name not in enabled_skills():
                    enable_skill(skill_name)
                    agent.refresh_skills()
                    print(f"Skill {cyan('/' + skill_name)} enabled. Conversation history was reset.")
                user_input = f"Follow the /{skill_name} skill instructions in your system prompt."
                if skill_args.strip():
                    user_input += f" Arguments: {skill_args.strip()}"
            if user_input.startswith("/"):
                print(red(f"no such command: {user_input.split()[0]}"))
                continue

            try:
                agent.run_turn(user_input)
            except Exception as e:
                # Keep the session and its history; the user can retry the prompt
                print(red(f"Request failed: {getattr(e, 'message', None) or e}"))
        except (KeyboardInterrupt, EOFError):
            print(cyan("\nGoodbye!"))
            break


if __name__ == "__main__":
    main()
