#!/usr/bin/env bash
set -e

echo "==> Code Shellie Installer"

# Run from the project root regardless of where this script was invoked from
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

# 1. Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required but not found."
    exit 1
fi

# 2. Create virtual environment if missing or broken (venv scripts pin an absolute path,
#    so a venv created under an old project path fails pip and must be rebuilt)
if ! ./venv/bin/pip --version &> /dev/null; then
    echo "==> Creating Python virtual environment..."
    rm -rf venv
    python3 -m venv venv
fi

# 3. Upgrade pip and install package in editable mode
echo "==> Installing dependencies and package..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -e .

# 4. Create ~/.local/bin if not exists
INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"

# 5. Remove the old command name from earlier installs (only if it is a symlink)
if [ -L "$INSTALL_DIR/shellie-code" ]; then
    echo "==> Removing old shellie-code link..."
    rm -f "$INSTALL_DIR/shellie-code"
fi

# 6. Create symlink
SYMLINK_PATH="$INSTALL_DIR/codesh"
TARGET_PATH="$PROJECT_DIR/venv/bin/codesh"

echo "==> Linking codesh to $SYMLINK_PATH..."
ln -sf "$TARGET_PATH" "$SYMLINK_PATH"

# 7. Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo ""
    echo "⚠️  WARNING: $HOME/.local/bin is not in your PATH."
    echo "Add the following line to your ~/.bashrc or ~/.zshrc:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
fi

echo ""
echo "✨ Installation complete! You can now run 'codesh' from anywhere."
