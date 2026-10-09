import re
import subprocess
import sys
from pathlib import Path

import code_shellie
from code_shellie import mcp_client

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def pyproject_version():
    match = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1)


def test_version_matches_pyproject():
    # Fails after a version bump until the package is reinstalled (pip install -e .)
    assert code_shellie.__version__ == pyproject_version()


def test_mcp_client_reports_the_same_version():
    assert mcp_client.CLIENT_INFO["version"] == code_shellie.__version__


def test_codesh_version_flag():
    out = subprocess.run([sys.executable, "-m", "code_shellie.cli", "--version"],
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == f"codesh {pyproject_version()}"
