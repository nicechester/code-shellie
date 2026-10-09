"""Line editor for the REPL on the terminal, using termios (stdlib).

Keys: Enter submits; Alt+Enter or Ctrl+J inserts a newline; pasted text (bracketed paste)
is inserted as-is, so it never submits early; Tab completes; Ctrl+O calls the view toggle;
Backspace deletes; Ctrl+U clears the line; Ctrl+C raises KeyboardInterrupt; Ctrl+D on an
empty line raises EOFError. Editing happens at the end of the input only.

When stdin is not a terminal, falls back to plain input() (no completion, no Ctrl+O).
"""
import codecs
import os
import re
import shutil
import sys
from typing import Callable, List, Optional, Tuple

from .term import dim

PROMPT = "\x1b[1;32mcodesh>\x1b[0m "
CONTINUATION = "\x1b[1;32m...\x1b[0m "
PASTE_START = "\x1b[200~"
PASTE_END = "\x1b[201~"
MAX_LISTED = 20

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

Completer = Callable[[str], Tuple[int, List[str]]]


def _visible_len(text: str) -> int:
    return len(_ANSI_RE.sub("", text))


def _partial_suffix(text: str, marker: str) -> int:
    """Length of the longest tail of text that is a proper prefix of marker (an incomplete marker)."""
    for k in range(min(len(marker) - 1, len(text)), 0, -1):
        if text.endswith(marker[:k]):
            return k
    return 0


def _escape_length(text: str) -> int:
    """Length of the escape sequence at the start of text, or 0 if it is not complete yet."""
    if len(text) < 2:
        return 0
    if text[1] == "[":
        for i in range(2, len(text)):
            if 0x40 <= ord(text[i]) <= 0x7E:
                return i + 1
        return 0
    if text[1] == "O":
        return 3 if len(text) >= 3 else 0
    return 2  # Alt+key, or Alt+Enter (ESC CR)


class LineEditor:
    def __init__(self, completer: Optional[Completer] = None, on_toggle_view: Optional[Callable[[], str]] = None):
        self.completer = completer
        self.on_toggle_view = on_toggle_view
        self.buf = ""
        self._rows_up = 0          # terminal rows between the first and the last row of the current rendering
        self._pending = ""         # input read but not handled yet (an escape sequence may be split across reads)
        self._in_paste = False
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def read(self) -> str:
        """Read one submitted input (may contain newlines). Raises KeyboardInterrupt or EOFError."""
        if not sys.stdin.isatty():
            return input("codesh> ")

        import termios

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        raw = termios.tcgetattr(fd)
        raw[3] &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN)  # no echo, per-key input, no Ctrl+V
        raw[0] &= ~(termios.ICRNL | termios.IXON)                      # Enter is CR, Ctrl+J is LF
        termios.tcsetattr(fd, termios.TCSADRAIN, raw)
        self._write("\x1b[?2004h")  # bracketed paste on
        try:
            self.buf = ""
            self._rows_up = 0
            self._render()
            while True:
                chunk = os.read(fd, 1024)
                if not chunk:
                    raise EOFError
                submitted = self._process(self._decoder.decode(chunk))
                if submitted is not None:
                    return submitted
                self._render()
        finally:
            self._write("\x1b[?2004l")
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    # Input handling

    def _process(self, text: str) -> Optional[str]:
        """Handle the input read so far. Returns the submitted text on Enter, else None."""
        self._pending += text
        while self._pending:
            s = self._pending
            if self._in_paste:
                end = s.find(PASTE_END)
                if end == -1:
                    keep = _partial_suffix(s, PASTE_END)
                    self._insert(_normalize_newlines(s[:len(s) - keep]))
                    self._pending = s[len(s) - keep:]
                    return None
                self._insert(_normalize_newlines(s[:end]))
                self._pending = s[end + len(PASTE_END):]
                self._in_paste = False
                continue
            if s.startswith(PASTE_START):
                self._in_paste = True
                self._pending = s[len(PASTE_START):]
                continue
            if s[0] == "\x1b":
                n = _escape_length(s)
                if n == 0:
                    return None  # wait for the rest of the sequence
                if s[:2] in ("\x1b\r", "\x1b\n"):
                    self._insert("\n")  # Alt+Enter
                self._pending = s[n:]
                continue

            self._pending = s[1:]
            if s[0] == "\r":
                self._write("\r\n")
                submitted, self.buf = self.buf, ""
                self._rows_up = 0
                return submitted
            if s[0] == "\n":
                self._insert("\n")  # Ctrl+J
            elif s[0] in ("\x7f", "\x08"):
                self.buf = self.buf[:-1]
            elif s[0] == "\x03":
                self._write("\r\n")
                self.buf = ""
                raise KeyboardInterrupt
            elif s[0] == "\x04":
                if not self.buf:
                    raise EOFError
            elif s[0] == "\x0f":
                self._toggle_view()
            elif s[0] == "\t":
                self._complete()
            elif s[0] == "\x15":
                self.buf = ""
            elif s[0] >= " ":
                self._insert(s[0])
        return None

    def _insert(self, text: str) -> None:
        self.buf += text

    def _toggle_view(self) -> None:
        if self.on_toggle_view is None:
            return
        view = self.on_toggle_view()
        self._write("\r\n" + dim(f"Output view: {view}") + "\r\n")
        self._rows_up = 0

    def _complete(self) -> None:
        if self.completer is None:
            return
        replace, candidates = self.completer(self.buf)
        if not candidates:
            return
        if len(candidates) == 1:
            suffix = candidates[0] if candidates[0].endswith("/") else candidates[0] + " "
            self.buf = self.buf[:len(self.buf) - replace] + suffix
            return
        common = os.path.commonprefix(candidates)
        if len(common) > replace:
            self.buf = self.buf[:len(self.buf) - replace] + common
            return
        listed = candidates[:MAX_LISTED]
        more = f"  ... {len(candidates) - MAX_LISTED} more" if len(candidates) > MAX_LISTED else ""
        self._write("\r\n" + "  ".join(listed) + more + "\r\n")
        self._rows_up = 0

    # Drawing

    def _render(self) -> None:
        """Redraw the prompt and the input, starting from the first row of the previous drawing."""
        up = f"\x1b[{self._rows_up}A" if self._rows_up else ""
        self._write("\r" + up + "\x1b[J")
        width = max(20, shutil.get_terminal_size((80, 24)).columns)
        lines = []
        rows = 0
        for i, line in enumerate(self.buf.split("\n")):
            shown = (PROMPT if i == 0 else CONTINUATION) + line
            lines.append(shown)
            rows += max(1, -(-_visible_len(shown) // width))
        self._write("\r\n".join(lines))
        self._rows_up = rows - 1

    def _write(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
