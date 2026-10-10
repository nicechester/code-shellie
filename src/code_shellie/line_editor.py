"""Line editor for the REPL on the terminal, using termios (stdlib).

Keys: Enter submits; Alt+Enter or Ctrl+J inserts a newline; pasted text (bracketed paste)
is inserted as-is, so it never submits early; Tab completes at the cursor; Ctrl+O calls the
view toggle; Left/Right move the cursor; Home/End or Ctrl+A/Ctrl+E go to the start/end of the
line; Up/Down move between lines of a multi-line input, and recall history on the first/last
line; Backspace deletes before the cursor; Delete or Ctrl+D (on a non-empty line) deletes under
it; Ctrl+U clears the line; Ctrl+C raises KeyboardInterrupt; Ctrl+D on an empty line raises EOFError.

History is kept in memory and, when a history_path is given, saved to that file on each submit.

When stdin is not a terminal, falls back to plain input() (no completion, no Ctrl+O, no history).
"""
import codecs
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .term import dim

PROMPT = "\x1b[1;32mcodesh>\x1b[0m "
CONTINUATION = "\x1b[1;32m...\x1b[0m "
PASTE_START = "\x1b[200~"
PASTE_END = "\x1b[201~"
MAX_LISTED = 20
MAX_HISTORY = 500

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# Escape sequences for cursor and history keys. Both the CSI (ESC [) and SS3 (ESC O) forms are listed,
# because terminals send one or the other depending on their mode.
_KEYS = {
    "\x1b[D": "left", "\x1bOD": "left",
    "\x1b[C": "right", "\x1bOC": "right",
    "\x1b[A": "up", "\x1bOA": "up",
    "\x1b[B": "down", "\x1bOB": "down",
    "\x1b[H": "home", "\x1bOH": "home", "\x1b[1~": "home", "\x1b[7~": "home",
    "\x1b[F": "end", "\x1bOF": "end", "\x1b[4~": "end", "\x1b[8~": "end",
    "\x1b[3~": "delete",
}

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


def _load_history(path: Path) -> List[str]:
    """Read saved history, one JSON string per line. Missing or unreadable files give an empty history."""
    entries = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, str):
                entries.append(value)
    except OSError:
        return []
    return entries[-MAX_HISTORY:]


class LineEditor:
    def __init__(self, completer: Optional[Completer] = None, on_toggle_view: Optional[Callable[[], str]] = None,
                 history_path: Optional[Path] = None):
        self.completer = completer
        self.on_toggle_view = on_toggle_view
        self.history_path = Path(history_path) if history_path else None
        self.history: List[str] = _load_history(self.history_path) if self.history_path else []
        self.buf = ""
        self.cursor = 0            # index into buf where the next character is inserted
        self._hist_pos = len(self.history)  # equals len(history) when not browsing history
        self._draft = ""           # the input being typed when history browsing started
        self._rows_up = 0          # terminal row of the cursor, counted from the first row of the current rendering
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
            self.cursor = 0
            self._hist_pos = len(self.history)
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
                key = _KEYS.get(s[:n])
                if key is not None:
                    self._move(key)
                elif s[:2] in ("\x1b\r", "\x1b\n"):
                    self._insert("\n")  # Alt+Enter
                self._pending = s[n:]
                continue

            self._pending = s[1:]
            if s[0] == "\r":
                self._write("\r\n")
                submitted, self.buf = self.buf, ""
                self.cursor = 0
                self._rows_up = 0
                self._remember(submitted)
                return submitted
            if s[0] == "\n":
                self._insert("\n")  # Ctrl+J
            elif s[0] in ("\x7f", "\x08"):
                if self.cursor > 0:
                    self.buf = self.buf[:self.cursor - 1] + self.buf[self.cursor:]
                    self.cursor -= 1
            elif s[0] == "\x03":
                self._write("\r\n")
                self.buf = ""
                self.cursor = 0
                raise KeyboardInterrupt
            elif s[0] == "\x04":
                if not self.buf:
                    raise EOFError
                self._delete()
            elif s[0] == "\x01":
                self._move("home")  # Ctrl+A
            elif s[0] == "\x05":
                self._move("end")   # Ctrl+E
            elif s[0] == "\x0f":
                self._toggle_view()
            elif s[0] == "\t":
                self._complete()
            elif s[0] == "\x15":
                self.buf = ""
                self.cursor = 0
            elif s[0] >= " ":
                self._insert(s[0])
        return None

    def _insert(self, text: str) -> None:
        self.buf = self.buf[:self.cursor] + text + self.buf[self.cursor:]
        self.cursor += len(text)

    def _delete(self) -> None:
        self.buf = self.buf[:self.cursor] + self.buf[self.cursor + 1:]

    def _line_start(self) -> int:
        return self.buf.rfind("\n", 0, self.cursor) + 1

    def _line_end(self) -> int:
        end = self.buf.find("\n", self.cursor)
        return len(self.buf) if end == -1 else end

    def _move(self, key: str) -> None:
        if key == "left":
            self.cursor = max(0, self.cursor - 1)
        elif key == "right":
            self.cursor = min(len(self.buf), self.cursor + 1)
        elif key == "home":
            self.cursor = self._line_start()
        elif key == "end":
            self.cursor = self._line_end()
        elif key == "delete":
            self._delete()
        elif key == "up":
            if self.buf.count("\n", 0, self.cursor) > 0:
                self._move_vertically(-1)
            else:
                self._recall(-1)
        elif key == "down":
            if self._line_end() < len(self.buf):
                self._move_vertically(1)
            else:
                self._recall(1)

    def _move_vertically(self, step: int) -> None:
        """Move to the same column on the previous (step -1) or next (step 1) line."""
        col = self.cursor - self._line_start()
        if step < 0:
            end = self._line_start() - 1  # the newline before the current line
            start = self.buf.rfind("\n", 0, end) + 1
        else:
            start = self._line_end() + 1
            end = self._line_end_from(start)
        self.cursor = start + min(col, end - start)

    def _line_end_from(self, start: int) -> int:
        end = self.buf.find("\n", start)
        return len(self.buf) if end == -1 else end

    def _recall(self, step: int) -> None:
        """Move through history: step -1 goes to older entries, step 1 to newer ones and then back to the draft."""
        if step < 0 and self._hist_pos > 0:
            if self._hist_pos == len(self.history):
                self._draft = self.buf
            self._hist_pos -= 1
            self.buf = self.history[self._hist_pos]
        elif step > 0 and self._hist_pos < len(self.history):
            self._hist_pos += 1
            self.buf = self.history[self._hist_pos] if self._hist_pos < len(self.history) else self._draft
        else:
            return
        self.cursor = len(self.buf)

    def _remember(self, text: str) -> None:
        """Add a submitted input to the history, skipping blank inputs and repeats of the last one."""
        self._hist_pos = len(self.history)
        if not text.strip() or (self.history and self.history[-1] == text):
            return
        self.history = (self.history + [text])[-MAX_HISTORY:]
        self._hist_pos = len(self.history)
        self._save_history()

    def _save_history(self) -> None:
        if self.history_path is None:
            return
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            self.history_path.write_text("".join(json.dumps(h) + "\n" for h in self.history), encoding="utf-8")
        except OSError:
            pass  # a read-only config directory must not break the REPL

    def _toggle_view(self) -> None:
        if self.on_toggle_view is None:
            return
        view = self.on_toggle_view()
        self._write("\r\n" + dim(f"Output view: {view}") + "\r\n")
        self._rows_up = 0

    def _complete(self) -> None:
        if self.completer is None:
            return
        replace, candidates = self.completer(self.buf[:self.cursor])
        if not candidates:
            return
        if len(candidates) == 1:
            suffix = candidates[0] if candidates[0].endswith("/") else candidates[0] + " "
            self._replace_before_cursor(replace, suffix)
            return
        common = os.path.commonprefix(candidates)
        if len(common) > replace:
            self._replace_before_cursor(replace, common)
            return
        listed = candidates[:MAX_LISTED]
        more = f"  ... {len(candidates) - MAX_LISTED} more" if len(candidates) > MAX_LISTED else ""
        self._write("\r\n" + "  ".join(listed) + more + "\r\n")
        self._rows_up = 0

    def _replace_before_cursor(self, count: int, text: str) -> None:
        start = self.cursor - count
        self.buf = self.buf[:start] + text + self.buf[self.cursor:]
        self.cursor = start + len(text)

    # Drawing

    def _render(self) -> None:
        """Redraw the prompt and the input, starting from the row the cursor was on, and leave the cursor at self.cursor."""
        up = f"\x1b[{self._rows_up}A" if self._rows_up else ""
        self._write("\r" + up + "\x1b[J")
        width = max(20, shutil.get_terminal_size((80, 24)).columns)
        cursor_line = self.buf.count("\n", 0, self.cursor)
        lines = []
        rows = 0
        cursor_row = cursor_col = 0
        line_start = 0
        for i, line in enumerate(self.buf.split("\n")):
            prefix = PROMPT if i == 0 else CONTINUATION
            shown = prefix + line
            lines.append(shown)
            line_rows = max(1, -(-_visible_len(shown) // width))
            if i == cursor_line:
                offset = _visible_len(prefix) + self.cursor - line_start
                wrapped = min(offset // width, line_rows - 1)
                cursor_row = rows + wrapped
                cursor_col = min(offset - wrapped * width, width - 1)
            rows += line_rows
            line_start += len(line) + 1
        self._write("\r\n".join(lines))
        # The terminal cursor is now at the end of the last row; move it to where the editing cursor is
        up_rows = rows - 1 - cursor_row
        self._write((f"\x1b[{up_rows}A" if up_rows else "") + "\r" + f"\x1b[{cursor_col + 1}G")
        self._rows_up = cursor_row

    def _write(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
