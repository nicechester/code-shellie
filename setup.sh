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
STAGE=""
BACKUP_DIR=""
ROLLBACK_SOURCE=0

cleanup_update() {
    local status=$?
    trap - EXIT
    if [ "$ROLLBACK_SOURCE" -eq 1 ] && [ "$status" -ne 0 ]; then
        rm -rf "$INSTALL_HOME/src" 2>/dev/null || true
        if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
            mv "$BACKUP_DIR" "$INSTALL_HOME/src" 2>/dev/null || true
            if [ -x "$INSTALL_HOME/venv/bin/pip" ]; then
                "$INSTALL_HOME/venv/bin/pip" install --no-deps -e "$INSTALL_HOME/src" >/dev/null 2>&1 || true
            fi
        fi
    elif [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
        rm -rf "$BACKUP_DIR" 2>/dev/null || true
    fi
    if [ -n "$STAGE" ] && [ -d "$STAGE" ]; then
        rm -rf "$STAGE" 2>/dev/null || true
    fi
    exit "$status"
}
trap cleanup_update EXIT

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
    mkdir -p "$INSTALL_HOME"
    STAGE="$(mktemp -d "$INSTALL_HOME/.codesh-stage.XXXXXX")"
    echo "==> Downloading Code Shellie ($REF)..."
    if ! curl -fsSL "$ARCHIVE_URL" | tar -xz -C "$STAGE" --strip-components=1; then
        echo "Error: could not download $ARCHIVE_URL. Check CODESH_REF and your network connection."
        exit 1
    fi
    if [ ! -f "$STAGE/pyproject.toml" ]; then
        echo "Error: the downloaded archive is not a Code Shellie source tree."
        exit 1
    fi

    # Keep the old source until the existing venv has installed the staged copy successfully.
    BACKUP_DIR="$INSTALL_HOME/.codesh-src-backup.$$"
    if [ -d "$INSTALL_HOME/src" ]; then
        mv "$INSTALL_HOME/src" "$BACKUP_DIR"
    else
        BACKUP_DIR=""
    fi
    ROLLBACK_SOURCE=1
    mv "$STAGE" "$INSTALL_HOME/src"
    STAGE=""
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
if ! "$VENV_DIR/bin/pip" install --upgrade pip || ! "$VENV_DIR/bin/pip" install -e "$SRC_DIR"; then
    echo "Error: package installation failed. Restoring the previous source."
    exit 1
fi

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

# From here the new source and venv are usable. Keep them and remove the backup.
ROLLBACK_SOURCE=0
if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
    rm -rf "$BACKUP_DIR"
fi

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
