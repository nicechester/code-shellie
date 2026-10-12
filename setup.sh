#!/usr/bin/env bash
# Code Shellie installer. The real installer; install.sh is a small stub that
# fetches this file (from the release, when one exists) and runs it. Run it
# directly from a checkout, or through install.sh.
set -eo pipefail

echo "==> Code Shellie Installer"

# 1. Check Python 3.8 or newer before anything else
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required but not found. Install Python 3.8 or newer, then run this again."
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))'; then
    echo "Error: Python 3.8 or newer is required, but found $(python3 -V 2>&1)."
    exit 1
fi

INSTALL_HOME="$HOME/.local/share/codesh"

# 2. Find the source. In a checkout, install that tree. Under 'curl | bash' there is no script file,
#    so download the GitHub archive for CODESH_REF (default main) and install from that.
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
if [ -n "$SCRIPT_PATH" ] && [ -f "$SCRIPT_PATH" ] && grep -q '^name = "code-shellie"' "$(dirname "$SCRIPT_PATH")/pyproject.toml" 2>/dev/null; then
    SRC_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
    VENV_DIR="$SRC_DIR/venv"
    echo "==> Installing from the checkout at $SRC_DIR"
else
    if ! command -v curl &> /dev/null; then
        echo "Error: curl is required to download Code Shellie."
        exit 1
    fi
    REF="${CODESH_REF:-main}"
    ARCHIVE_URL="${CODESH_ARCHIVE_URL:-https://github.com/nicechester/code-shellie/archive/${REF}.tar.gz}"

    # Download and unpack into a staging directory first, so a failed download leaves the current install alone
    STAGE="$(mktemp -d)"
    trap 'rm -rf "$STAGE"' EXIT
    echo "==> Downloading Code Shellie ($REF)..."
    if ! curl -fsSL "$ARCHIVE_URL" | tar -xz -C "$STAGE" --strip-components=1; then
        echo "Error: could not download $ARCHIVE_URL. Check CODESH_REF and your network connection."
        exit 1
    fi
    if [ ! -f "$STAGE/pyproject.toml" ]; then
        echo "Error: the downloaded archive is not a Code Shellie source tree."
        exit 1
    fi

    # Replace the old source wholesale, so no stale files are left behind. The venv is kept and reused.
    mkdir -p "$INSTALL_HOME"
    rm -rf "$INSTALL_HOME/src"
    mv "$STAGE" "$INSTALL_HOME/src"
    SRC_DIR="$INSTALL_HOME/src"
    VENV_DIR="$INSTALL_HOME/venv"
    echo "==> Installed source into $SRC_DIR"
fi

# 3. Create the virtual environment if missing or broken (venv scripts pin an absolute path,
#    so a venv created under an old path fails pip and must be rebuilt)
if ! "$VENV_DIR/bin/pip" --version &> /dev/null; then
    echo "==> Creating Python virtual environment..."
    rm -rf "$VENV_DIR"
    python3 -m venv "$VENV_DIR"
fi

# 4. Upgrade pip and install package in editable mode
echo "==> Installing dependencies and package..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -e "$SRC_DIR"

# 5. Create ~/.local/bin if not exists
INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"

# 6. Remove the old command name from earlier installs (only if it is a symlink)
if [ -L "$INSTALL_DIR/shellie-code" ]; then
    echo "==> Removing old shellie-code link..."
    rm -f "$INSTALL_DIR/shellie-code"
fi

# 7. Create symlink
SYMLINK_PATH="$INSTALL_DIR/codesh"
TARGET_PATH="$VENV_DIR/bin/codesh"

echo "==> Linking codesh to $SYMLINK_PATH..."
ln -sf "$TARGET_PATH" "$SYMLINK_PATH"

# 8. Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo ""
    echo "⚠️  WARNING: $HOME/.local/bin is not in your PATH."
    echo "Add the following line to your ~/.bashrc or ~/.zshrc:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
fi

echo ""
echo "✨ Installation complete! You can now run 'codesh' from anywhere."
