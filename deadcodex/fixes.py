"""Fix plans: how a finding's fix turns into concrete line edits. Pure functions, no I/O.

Plan formats (stored as JSON on Finding.plan):
  {"op":"delete_lines","start":S,"end":E}                       remove lines S..E (1-based, inclusive)
  {"op":"replace_lines","start":S,"end":E,"text":T}             replace lines S..E with text T (one line)
  {"op":"py_import", ...}   rewrite/remove part of a Python import statement
  {"op":"js_import", ...}   rewrite/remove part of a JS/TS import / require statement
  {"op":"delete_path","path":REL,"is_dir":bool}                 remove a file or directory
"""
from __future__ import annotations

import ast
import difflib
import shutil
from pathlib import Path


# ------------------------------------------------------------------ rendering of partial import edits
def _fmt_py_alias(name, asname):
    return f"{name} as {asname}" if asname else name


def render_py_import(plan: dict, removed: set) -> list:
    keep = [a for i, a in enumerate(plan["aliases"]) if i not in removed]
    if not keep:
        return [f"{plan['indent']}pass\n"] if plan.get("sole") else []
    names = ", ".join(_fmt_py_alias(*a) for a in keep)
    if plan["kind"] == "import":
        return [f"{plan['indent']}import {names}\n"]
    return [f"{plan['indent']}from {plan['module']} import {names}\n"]


def render_js_import(plan: dict, removed: set) -> list:
    default = None if "default" in removed else plan.get("default")
    ns = None if "ns" in removed else plan.get("namespace")
    named = [p for p in plan.get("named", []) if f"n:{p[1]}" not in removed]
    if not (default or ns or named):
        return []
    q, semi = plan.get("quote", "'"), ";" if plan.get("semi", True) else ""
    indent = plan.get("indent", "")
    if plan["style"] == "require":
        if default:
            lhs = default
        else:
            inner = ", ".join(p[0] if p[0] == p[1] else f"{p[0]}: {p[1]}" for p in named)
            lhs = "{ " + inner + " }"
        return [f"{indent}{plan.get('decl', 'const')} {lhs} = require({q}{plan['module']}{q}){semi}\n"]
    parts = []
    if default:
        parts.append(default)
    if ns:
        parts.append(f"* as {ns}")
    if named:
        parts.append("{ " + ", ".join(("type " if len(p) > 2 and p[2] else "") + (p[0] if p[0] == p[1] else f"{p[0]} as {p[1]}") for p in named) + " }")
    kw = "import type" if plan.get("type_only") else "import"
    return [f"{indent}{kw} {', '.join(parts)} from {q}{plan['module']}{q}{semi}\n"]


def js_remove_key(plan: dict) -> str:
    return plan["remove"][0]


# ------------------------------------------------------------------ building edits
def build_edits(plans: list) -> tuple:
    """plans: list of (finding_id, plan). Returns (edits, owner, skipped)
    edits: [(start, end, new_lines, [finding_ids])] non-overlapping, sorted by start
    skipped: [(finding_id, reason)]"""
    groups = {}  # (start,end,op) -> list of (fid, plan)
    order = []
    for fid, plan in plans:
        key = (plan["start"], plan["end"], plan["op"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((fid, plan))
    raw = []
    for key in order:
        start, end, op = key
        items = groups[key]
        ids = [fid for fid, _ in items]
        base = items[0][1]
        if op == "delete_lines":
            raw.append((start, end, [], ids))
        elif op == "replace_lines":
            raw.append((start, end, [base["text"]], ids))
        elif op == "py_import":
            removed = {r for _, p in items for r in p["remove"]}
            raw.append((start, end, render_py_import(base, removed), ids))
        elif op == "js_import":
            removed = {r for _, p in items for r in p["remove"]}
            raw.append((start, end, render_js_import(base, removed), ids))
    raw.sort(key=lambda e: (e[0], -(e[1] - e[0])))
    edits, skipped = [], []
    for e in raw:
        if edits and e[0] <= edits[-1][1]:
            prev = edits[-1]
            reason = ("covered by a larger selected fix on the same lines" if e[1] <= prev[1]
                      else "overlaps another selected fix on the same lines")
            skipped.extend((fid, reason) for fid in e[3])
        else:
            edits.append(e)
    return edits, skipped


def apply_edits(lines: list, edits: list) -> list:
    """lines are 'with newline' strings. Edits must be non-overlapping."""
    out = list(lines)
    for start, end, new, _ in sorted(edits, key=lambda e: -e[0]):
        out[start - 1:end] = new
    return out


def preview_window(lines: list, plan: dict, context: int) -> tuple:
    """(before_text, after_text) for one finding's plan, windowed with `context` lines. Real code only."""
    start, end = plan["start"], plan["end"]
    if plan["op"] == "delete_lines":
        new = []
    elif plan["op"] == "replace_lines":
        new = [plan["text"]]
    elif plan["op"] == "py_import":
        new = render_py_import(plan, set(plan["remove"]))
    elif plan["op"] == "js_import":
        new = render_js_import(plan, set(plan["remove"]))
    else:
        return None, None
    lo = max(1, start - context)
    hi = min(len(lines), end + context)
    before = [f"{n:>4} | {lines[n - 1].rstrip(chr(10))}" for n in range(lo, hi + 1)]
    after_lines = lines[lo - 1:start - 1] + new + lines[end:hi]
    first = lo
    after = []
    for k, l in enumerate(after_lines):
        after.append(f"{first + k:>4} | {l.rstrip(chr(10))}")
    if not after_lines:
        after = ["     | (nothing left here)"]
    return "\n".join(before), "\n".join(after)


# ------------------------------------------------------------------ diffs and validation
def unified_diff(rel: str, old: str, new: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}", n=2))


def validate_text(language: str, rel: str, text: str) -> tuple:
    """Syntax validation that never executes code. Returns (ok, message)."""
    if language == "python":
        try:
            ast.parse(text, filename=rel)
            return True, "Python syntax OK (ast.parse)"
        except SyntaxError as e:
            return False, f"SyntaxError line {e.lineno}: {e.msg}"
        except (ValueError, RecursionError) as e:
            return False, f"cannot parse: {e}"
    if language in ("javascript", "typescript"):
        from .analyzer.jsscan import scan_js

        jsx = rel.endswith(("x",))
        v = scan_js(text, jsx=jsx)
        if not v.ok:
            return False, "brackets/strings no longer balance"
        return True, "JS/TS structure OK (balanced brackets, terminated strings; no full parser available)"
    return True, "no syntax check for this file type"


def language_of(rel: str):
    ext = Path(rel).suffix.lower()
    if ext == ".py":
        return "python"
    if ext in (".js", ".jsx", ".mjs", ".cjs"):
        return "javascript"
    if ext in (".ts", ".tsx"):
        return "typescript"
    return None


def remove_path(path: Path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
