#!/usr/bin/env bash
# Code Shellie installer entry point. Keep this file small: it is the target of
# the one-line install, so its URL must not change.
#
#   curl -fsSL https://raw.githubusercontent.com/nicechester/code-shellie/main/install.sh | bash
#   ./install.sh                                  from a checkout
#
# Outside a checkout, this fetches setup.sh from the latest release (or the
# CODESH_REF release), so each install is counted on that asset. If no release
# asset exists, it fetches setup.sh from the requested ref instead.
set -eo pipefail

REPO="nicechester/code-shellie"
SCRIPT_PATH="${BASH_SOURCE[0]:-}"

# From a checkout: run the checkout's installer directly.
if [ -n "$SCRIPT_PATH" ] && [ -f "$SCRIPT_PATH" ]; then
    HERE="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
    if [ -f "$HERE/setup.sh" ] && [ -f "$HERE/pyproject.toml" ]; then
        exec bash "$HERE/setup.sh" "$@"
    fi
fi

if ! command -v curl &> /dev/null; then
    echo "Error: curl is required to download Code Shellie."
    exit 1
fi

if [ -n "${CODESH_REF:-}" ]; then
    ASSET_URL="https://github.com/$REPO/releases/download/$CODESH_REF/setup.sh"
    RAW_URL="https://raw.githubusercontent.com/$REPO/$CODESH_REF/setup.sh"
else
    ASSET_URL="https://github.com/$REPO/releases/latest/download/setup.sh"
    RAW_URL="https://raw.githubusercontent.com/$REPO/main/setup.sh"
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
if ! curl -fsSL "$ASSET_URL" -o "$TMP" 2>/dev/null; then
    curl -fsSL "$RAW_URL" -o "$TMP"
fi
bash "$TMP" "$@"
