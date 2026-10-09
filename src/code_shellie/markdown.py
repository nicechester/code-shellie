"""Terminal rendering of a Markdown answer, on the stdlib. Colors come from term.py and are dropped when not on a terminal.

Covers the parts models use most: headings, fenced code blocks, bullet and numbered lists,
block quotes, rules, and inline `code`, **bold** and *italic*. Anything else is printed as written.
"""
import re

from .term import bold, cyan, dim, italic

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_RULE_RE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_INLINE_RE = re.compile(r"(`[^`\n]+`|\*\*[^*\n]+\*\*|(?<![\w*])\*[^*\n]+\*(?![\w*]))")


def _inline(text: str) -> str:
    def style(match):
        token = match.group(0)
        if token.startswith("`"):
            return cyan(token[1:-1])
        if token.startswith("**"):
            return bold(token[2:-2])
        return italic(token[1:-1])
    return _INLINE_RE.sub(style, text)


def render(text: str) -> str:
    out = []
    in_code = False
    for line in text.split("\n"):
        if _FENCE_RE.match(line):
            in_code = not in_code
            continue
        if in_code:
            out.append(dim("    " + line))
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            out.append(bold(_inline(heading.group(2))))
            continue
        if _RULE_RE.match(line):
            out.append(dim("─" * 40))
            continue
        quote = _QUOTE_RE.match(line)
        if quote:
            out.append(dim("│ ") + _inline(quote.group(1)))
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            out.append(bullet.group(1) + "• " + _inline(bullet.group(2)))
            continue
        numbered = _NUMBERED_RE.match(line)
        if numbered:
            out.append(numbered.group(1) + numbered.group(2) + ". " + _inline(numbered.group(3)))
            continue
        out.append(_inline(line))
    return "\n".join(out)
