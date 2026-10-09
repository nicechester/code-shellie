"""ANSI styling for terminal output. Colors are dropped when stdout is not a terminal or NO_COLOR is set."""
import os
import sys

_CODES = {"bold": "1", "dim": "2", "italic": "3", "red": "31", "green": "32", "yellow": "33", "blue": "34", "cyan": "36"}


def _enabled() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def paint(text: str, *styles: str) -> str:
    if not _enabled() or not styles:
        return text
    codes = ";".join(_CODES[s] for s in styles)
    return f"\x1b[{codes}m{text}\x1b[0m"


def bold(text: str) -> str:
    return paint(text, "bold")


def dim(text: str) -> str:
    return paint(text, "dim")


def italic(text: str) -> str:
    return paint(text, "italic")


def red(text: str) -> str:
    return paint(text, "red")


def green(text: str) -> str:
    return paint(text, "green")


def yellow(text: str) -> str:
    return paint(text, "yellow")


def cyan(text: str) -> str:
    return paint(text, "cyan")


def blue(text: str) -> str:
    return paint(text, "blue")
