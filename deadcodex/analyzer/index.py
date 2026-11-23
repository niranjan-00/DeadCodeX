"""Project-wide reference index: which identifiers / file names appear where.

Counts are used as *evidence*: a symbol with zero references anywhere is reported with high confidence;
a symbol that only appears inside strings (getattr/url_for/entry points) is reported as potential.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .common import (DOC_TEXT_EXTS, JS_EXTS, MAX_SOURCE_BYTES, OTHER_CODE_TEXT_EXTS, PY_EXTS, SPECIAL_TEXT_NAMES, TS_EXTS, Project,
                     read_text)
from .jsscan import WORD_RE, JsView, scan_js

FILE_REF_RE = re.compile(r"[\w@%+~.\-/]+\.[A-Za-z0-9]{1,8}\b")
PY_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
DOTTED_RE = re.compile(r"^[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+$")

_DYN_PY = [
    ("eval()/exec()", re.compile(r"\b(?:eval|exec)\s*\(")),
    ("__import__(<non-literal>)", re.compile(r"\b__import__\s*\(\s*[^'\"\s)]")),
    ("importlib.import_module(<non-literal>)", re.compile(r"\bimport_module\s*\(\s*[^'\"\s)]")),
    ("getattr(obj, <non-literal>)", re.compile(r"\bgetattr\s*\(\s*[^,()]+,\s*[^'\"\s)]")),
    ("setattr(obj, <non-literal>)", re.compile(r"\bsetattr\s*\(\s*[^,()]+,\s*[^'\"\s)]")),
    ("globals()/locals()[...]", re.compile(r"\b(?:globals|locals|vars)\s*\(\s*\)\s*\[")),
]
_DYN_JS = [
    ("eval() / new Function()", re.compile(r"\beval\s*\(|\bnew\s+Function\s*\(")),
    ("require(<non-literal>)", re.compile(r"\brequire\s*\(\s*[^'\"\s)]")),
    ("import(<non-literal>)", re.compile(r"\bimport\s*\(\s*[^'\"\s)]")),
    ("window[...] / globalThis[...]", re.compile(r"\b(?:window|globalThis|global)\s*\[")),
]


@dataclass
class ProjectIndex:
    code_words: Counter = field(default_factory=Counter)
    other_words: Counter = field(default_factory=Counter)
    string_words: Counter = field(default_factory=Counter)  # python string literals
    ref_basenames: set = field(default_factory=set)
    ref_paths: set = field(default_factory=set)
    all_words: set = field(default_factory=set)
    imports_py: set = field(default_factory=set)
    js_specs: list = field(default_factory=list)  # (importing rel, specifier)
    dynamic_py: list = field(default_factory=list)  # (feature, rel, count)
    dynamic_js: list = field(default_factory=list)
    syntax_errors: list = field(default_factory=list)  # (rel, message)
    file_strings: dict = field(default_factory=dict)  # rel -> list of string literal contents (python) for evidence
    js_views: dict = field(default_factory=dict)
    py_top_modules: set = field(default_factory=set)
    loc: dict = field(default_factory=dict)  # language -> lines
    files_by_lang: dict = field(default_factory=dict)
    string_dirs_dynamic: list = field(default_factory=list)  # (rel, string) strings that look like templated paths
    n_code_files: int = 0
    n_other_files: int = 0
    _py_rows: dict = field(default_factory=dict)
    _js_rows: dict = field(default_factory=dict)

    # ------------- evidence helpers
    def refs_total(self, name: str) -> int:
        return self.code_words[name] + self.other_words[name]

    def py_name_rows(self, rel, src=None):
        rows = self._py_rows.get(rel)
        if rows is None:
            rows = defaultdict(list)
            for kind, word, row in py_tokens(src if src is not None else (read_text(self._abs[rel], MAX_SOURCE_BYTES) or "")):
                if kind == "NAME":
                    rows[word].append(row)
            self._py_rows[rel] = rows
        return rows

    def js_name_rows(self, rel):
        rows = self._js_rows.get(rel)
        if rows is None:
            rows = defaultdict(list)
            view = self.js_views.get(rel)
            text = view.nocomment if view else scan_js(read_text(self._abs[rel], MAX_SOURCE_BYTES) or "", jsx=rel.endswith("x")).nocomment
            for ln, line in enumerate(text.split("\n"), 1):
                for w in WORD_RE.findall(line):
                    rows[w].append(ln)
            self._js_rows[rel] = rows
        return rows

    def own_refs(self, rel, lang, name, start, end) -> int:
        rows = self.py_name_rows(rel) if lang == "python" else self.js_name_rows(rel)
        return sum(1 for r in rows.get(name, ()) if start <= r <= end)

    def external_refs(self, rel, lang, name, start, end) -> int:
        return max(0, self.refs_total(name) - self.own_refs(rel, lang, name, start, end))

    def string_ref_location(self, name: str):
        pat = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])")
        for rel, strings in self.file_strings.items():
            for s in strings:
                if pat.search(s):
                    return rel, s[:80]
        return None

    _abs: dict = field(default_factory=dict)


def py_tokens(src: str):
    """Yield (kind, text, row): NAME tokens, plus STR tokens (string literal contents).
    f-string expression parts are reported as NAME (they are code)."""
    fstring_mid = getattr(tokenize, "FSTRING_MIDDLE", None)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.NAME:
                yield "NAME", tok.string, tok.start[0]
            elif tok.type == tokenize.STRING:
                s = tok.string
                prefix = re.match(r"^[A-Za-z]*", s).group(0).lower()
                if "f" in prefix:  # py<3.12 f-string: {expr} is code
                    for w in PY_WORD_RE.findall(s):
                        yield "NAME", w, tok.start[0]
                else:
                    yield "STR", s, tok.start[0]
            elif fstring_mid is not None and tok.type == fstring_mid:
                yield "STR", tok.string, tok.start[0]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # fall back to a conservative word scan for the rest of the file
        for row, line in enumerate(src.split("\n"), 1):
            for w in PY_WORD_RE.findall(line):
                yield "NAME", w, row


def _imports_from_tree(tree, rel, out: set):
    pkg_parts = rel.split("/")[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                parts = a.name.split(".")
                for i in range(1, len(parts) + 1):
                    out.add(".".join(parts[:i]))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg_parts[: max(0, len(pkg_parts) - (node.level - 1))]
                mod = ".".join(base + (node.module.split(".") if node.module else []))
            else:
                mod = node.module or ""
            if mod:
                parts = mod.split(".")
                for i in range(1, len(parts) + 1):
                    out.add(".".join(parts[:i]))
            for a in node.names:
                out.add((mod + "." if mod else "") + a.name)


def build_index(project: Project, settings: dict, progress=None) -> ProjectIndex:
    idx = ProjectIndex()
    idx._abs = {f.rel: f.abs for f in project.files}
    total = max(1, len(project.files))
    js_bytes = 0
    for n, pf in enumerate(project.files):
        if progress and n % 200 == 0:
            progress(int(10 + 25 * n / total), f"Indexing references ({n}/{total} files)")
        lang = pf.lang
        ext = pf.ext
        if lang:
            idx.files_by_lang.setdefault(lang, []).append(pf.rel)
        is_text = lang or ext in OTHER_CODE_TEXT_EXTS or ext in DOC_TEXT_EXTS or pf.name.lower() in SPECIAL_TEXT_NAMES or pf.name.startswith(".env")
        if not is_text:
            continue
        limit = MAX_SOURCE_BYTES if lang else 1024 * 1024
        text = read_text(pf.abs, limit)
        if text is None:
            continue
        if lang:
            idx.n_code_files += 1
        else:
            idx.n_other_files += 1
        for m in FILE_REF_RE.findall(text):
            low = m.lower()
            idx.ref_basenames.add(low.rsplit("/", 1)[-1])
            if "/" in low:
                idx.ref_paths.add(low.lstrip("./"))
        if lang == "python":
            idx.loc["python"] = idx.loc.get("python", 0) + text.count("\n") + 1
            for feat, rx in _DYN_PY:
                c = len(rx.findall(text))
                if c:
                    idx.dynamic_py.append((feat, pf.rel, c))
            strings = []
            for kind, word, row in py_tokens(text):
                if kind == "NAME":
                    idx.code_words[word] += 1
                else:
                    strings.append(word)
                    for w in PY_WORD_RE.findall(word):
                        idx.string_words[w] += 1
                    inner = word.strip("\"'")
                    if DOTTED_RE.match(inner):
                        idx.imports_py.add(inner)
                    if ("{" in word or "%s" in word or "%(" in word) and "/" in word:
                        idx.string_dirs_dynamic.append((pf.rel, word))
            idx.file_strings[pf.rel] = strings
            try:
                tree = ast.parse(text, filename=pf.rel)
                _imports_from_tree(tree, pf.rel, idx.imports_py)
            except (SyntaxError, ValueError, RecursionError) as e:
                idx.syntax_errors.append((pf.rel, f"{type(e).__name__}: {getattr(e, 'msg', e)} (line {getattr(e, 'lineno', '?')})"))
            top = pf.rel.split("/")[0]
            idx.py_top_modules.add(top[:-3] if top.endswith(".py") else top)
        elif lang in ("javascript", "typescript"):
            if pf.name.endswith(".d.ts"):
                for w in WORD_RE.findall(text):
                    idx.code_words[w] += 1
                continue
            idx.loc[lang] = idx.loc.get(lang, 0) + text.count("\n") + 1
            view = scan_js(text, jsx=ext in (".jsx", ".tsx"))
            if js_bytes < 40 * 1024 * 1024:
                idx.js_views[pf.rel] = view
                js_bytes += len(text) * 2
            for w in WORD_RE.findall(view.nocomment):
                idx.code_words[w] += 1
            for tm in re.finditer(r"`[^`\n]*\$\{[^`\n]*`", view.nocomment):
                if "/" in tm.group(0) or "." in tm.group(0):
                    idx.string_dirs_dynamic.append((pf.rel, tm.group(0)))
            for feat, rx in _DYN_JS:
                c = len(rx.findall(view.code))
                if c:
                    idx.dynamic_js.append((feat, pf.rel, c))
            for m in re.finditer(r"""(?:from\s*|require\s*\(\s*|import\s*\(?\s*)(['"])([^'"\n]+)\1""", view.nocomment):
                if view.code[m.start():m.start() + 4] in ("from", "requ", "impo"):
                    idx.js_specs.append((pf.rel, m.group(2)))
        elif ext in OTHER_CODE_TEXT_EXTS or pf.name.lower() in SPECIAL_TEXT_NAMES or pf.name.startswith(".env"):
            for w in WORD_RE.findall(text):
                idx.other_words[w] += 1
            if ext in (".html", ".htm", ".vue", ".svelte", ".ejs"):
                idx.loc["markup"] = idx.loc.get("markup", 0) + text.count("\n") + 1
        # .md/.rst/.txt only contribute file-name references (collected above)
    idx.all_words = set(idx.code_words) | set(idx.other_words)
    return idx
