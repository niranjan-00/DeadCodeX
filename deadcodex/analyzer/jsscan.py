"""A small, forgiving JavaScript/TypeScript lexer.

It does NOT build an AST. It produces two same-length views of the source:
  code      - comments, strings, template text and regex literals blanked (structure: braces, keywords)
  nocomment - only comments blanked (strings kept; used for reference counting, which is deliberately
              conservative: a name that appears inside a string still counts as a reference)
and reports whether brackets balance (`ok`). Callers must treat `ok == False` as "could not parse reliably".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_REGEX_PREV_WORDS = {"return", "typeof", "case", "do", "else", "in", "of", "void", "delete", "throw", "new", "yield", "await", "instanceof"}
_REGEX_PREV_CHARS = set("(,=:[!&|?{};+-*%<>~^")
_IDENT_START = re.compile(r"[A-Za-z_$]")
_IDENT = re.compile(r"[A-Za-z0-9_$]")
WORD_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


@dataclass
class JsView:
    code: str
    nocomment: str
    ok: bool
    unterminated_strings: int = 0
    notes: list = field(default_factory=list)


def _blank(buf: list, a: int, b: int):
    for k in range(a, min(b, len(buf))):
        if buf[k] != "\n":
            buf[k] = " "


def scan_js(text: str, jsx: bool = False) -> JsView:
    n = len(text)
    code = list(text)
    nocomment = list(text)
    stack = []  # 'brace' | 'tmpl'
    depth_ok = True
    unterminated = 0
    prev_sig = ""
    prev_word = None
    i = 0

    def scan_template_body(start: int) -> int:
        """Scan template text from `start`; returns index after the closing backtick or after '${'."""
        nonlocal unterminated
        j = start
        while j < n:
            ch = text[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "`":
                _blank(code, start, j + 1)
                return j + 1
            if ch == "$" and j + 1 < n and text[j + 1] == "{":
                _blank(code, start, j + 2)
                stack.append("tmpl")
                return j + 2
            j += 1
        unterminated += 1
        _blank(code, start, n)
        return n

    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j == -1 else j
            _blank(code, i, j)
            _blank(nocomment, i, j)
            i = j
            continue
        if c == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            _blank(code, i, j)
            _blank(nocomment, i, j)
            i = j
            continue
        if c in "'\"":
            j = i + 1
            closed = False
            while j < n:
                ch = text[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == c:
                    closed = True
                    break
                if ch == "\n":
                    break
                j += 1
            if not closed:
                unterminated += 1
            _blank(code, i, j + 1 if closed else j)
            prev_sig, prev_word = "s", None
            i = j + 1 if closed else j
            continue
        if c == "`":
            _blank(code, i, i + 1)
            i = scan_template_body(i + 1)
            prev_sig, prev_word = "s", None
            continue
        if c == "{":
            stack.append("brace")
            prev_sig, prev_word = c, None
            i += 1
            continue
        if c == "}":
            if stack and stack[-1] == "tmpl":
                stack.pop()
                _blank(code, i, i + 1)
                i = scan_template_body(i + 1)
                prev_sig, prev_word = "s", None
                continue
            if stack and stack[-1] == "brace":
                stack.pop()
            else:
                depth_ok = False
            prev_sig, prev_word = c, None
            i += 1
            continue
        if c == "/":
            is_regex = False
            if prev_sig == "" or prev_sig in _REGEX_PREV_CHARS or (prev_word in _REGEX_PREV_WORDS):
                is_regex = True
            if prev_sig == "<" and jsx:
                is_regex = False  # closing JSX tag: </div>
            if prev_sig == "<":
                is_regex = False
            if is_regex:
                j = i + 1
                in_class = False
                closed = False
                while j < n:
                    ch = text[j]
                    if ch == "\\":
                        j += 2
                        continue
                    if ch == "\n":
                        break
                    if ch == "[":
                        in_class = True
                    elif ch == "]":
                        in_class = False
                    elif ch == "/" and not in_class:
                        closed = True
                        break
                    j += 1
                if closed:
                    j += 1
                    while j < n and _IDENT.match(text[j]):
                        j += 1
                    _blank(code, i, j)
                    prev_sig, prev_word = "s", None
                    i = j
                    continue
            prev_sig, prev_word = c, None
            i += 1
            continue
        if _IDENT_START.match(c):
            j = i + 1
            while j < n and _IDENT.match(text[j]):
                j += 1
            prev_word = text[i:j]
            prev_sig = "a"
            i = j
            continue
        if c.isdigit():
            j = i + 1
            while j < n and (_IDENT.match(text[j]) or text[j] == "."):
                j += 1
            prev_sig, prev_word = "n", None
            i = j
            continue
        if not c.isspace():
            prev_sig, prev_word = c, None
        i += 1

    code_s = "".join(code)
    # bracket balance on the structural view
    pairs = {")": "(", "]": "["}
    st = []
    ok = depth_ok and not stack
    for ch in code_s:
        if ch in "([":
            st.append(ch)
        elif ch in ")]":
            if not st or st[-1] != pairs[ch]:
                ok = False
                break
            st.pop()
    if st:
        ok = False
    if unterminated > 2:
        ok = False
    return JsView(code=code_s, nocomment="".join(nocomment), ok=ok, unterminated_strings=unterminated)


def bracket_signature(text: str, jsx: bool = False):
    """(ok, net counts) used to validate that an edit left the file structurally balanced."""
    v = scan_js(text, jsx=jsx)
    return v.ok, (v.code.count("{") - v.code.count("}"), v.code.count("(") - v.code.count(")"), v.code.count("[") - v.code.count("]"))
