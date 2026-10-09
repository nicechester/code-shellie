"""Code Shellie. The version comes from the installed package metadata, which is set from pyproject.toml."""
from importlib.metadata import PackageNotFoundError, version as _package_version

try:
    __version__ = _package_version("code-shellie")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"
