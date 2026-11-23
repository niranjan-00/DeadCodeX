"""Orchestrates a full analysis of a project directory and returns findings + summary."""
from __future__ import annotations

import hashlib
import os
from collections import Counter, defaultdict

from .. import settings_schema as S
from .common import CATEGORY_LABELS, discover, read_text, split_lines
from .explain import build_details
from .files_an import analyze_files
from .index import build_index
from .js_an import analyze_js
from .python_an import analyze_python

LIMITATIONS = [
    "Python is analyzed with the standard `ast` module (accurate syntax tree). JavaScript/TypeScript use a lexer + pattern rules, not a full parser, so they cover imports, top-level declarations, exports and unreachable statements only.",
    "Other languages (Java, C#, PHP, Ruby, Go, Vue/Svelte single-file components...) are not analyzed; their text is only searched for references to Python/JS names and asset file names.",
    "Static analysis cannot see dynamic access (getattr, importlib, eval, string-built paths, reflection, framework auto-discovery). Findings affected by such features are labelled 'potential'.",
    "Unused-variable detection covers simple assignments inside Python functions and top-level Python/JS variables; destructuring, loop variables and JS local variables are not reported.",
    "CSS rules, HTML elements and database migrations are not analyzed for dead code.",
    "Project tests are never executed (running uploaded code would be unsafe). Validation = syntax re-check of every changed file.",
]


def fingerprint(f) -> str:
    key = "|".join([f.category, f.file, f.symbol or "", (f.snippet or "").split("\n")[0].split("|", 1)[-1].strip()[:120]])
    return hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()


def _drop_nested(findings):
    """Remove code findings fully inside a larger removable finding, and code findings in files flagged for deletion."""
    whole_files = {f.file for f in findings if f.item_type == "file" and f.fix_mode != "manual" and f.category in ("duplicate_file", "junk_file", "unused_module", "unused_asset")}
    dirs = [f.file + "/" for f in findings if f.item_type == "dir"]
    containers = defaultdict(list)
    for f in findings:
        if f.item_type == "code" and f.category in ("unused_function", "unused_class", "unused_export", "dead_branch") and f.plan:
            containers[f.file].append(f)
    out = []
    for f in findings:
        if f.item_type == "code":
            if f.file in whole_files or any(f.file.startswith(d) for d in dirs):
                continue
            nested = False
            for c in containers.get(f.file, ()):
                if c is f:
                    continue
                if c.line <= f.line and f.end_line <= c.end_line and (c.end_line - c.line) > (f.end_line - f.line):
                    nested = True
                    break
            if nested:
                continue
        out.append(f)
    return out


def redundant_bytes(findings, root) -> int:
    total = 0
    by_file = defaultdict(list)
    for f in findings:
        if f.fix_mode == "manual":
            continue
        if f.item_type in ("file", "dir"):
            total += f.size_bytes
        else:
            by_file[f.file].append(f)
    for rel, fs in by_file.items():
        text = read_text(os.path.join(root, rel), 4 * 1024 * 1024)
        if text is None:
            continue
        lines = split_lines(text)
        covered = set()
        for f in fs:
            s, e = f.plan.get("start", f.line), f.plan.get("end", f.end_line)
            covered.update(range(s, e + 1))
        total += sum(len(lines[n - 1].encode("utf-8", "replace")) for n in covered if 1 <= n <= len(lines))
    return total


def run_analysis(root, settings: dict, progress=None) -> dict:
    progress = progress or (lambda p, m: None)
    progress(3, "Scanning project files")
    project = discover(root, settings)
    languages = set(settings.get("scan.languages", S.LANGUAGES))
    progress(8, "Building reference index")
    idx = build_index(project, settings, progress)
    pkg_dirs = {os.path.dirname(f.rel) for f in project.files if f.name == "__init__.py"}
    packaging = any(f.name in ("setup.py", "pyproject.toml", "setup.cfg") for f in project.files)
    ctx = {"library_like": lambda rel: packaging and os.path.dirname(rel) in pkg_dirs}
    findings, notes = [], Counter()
    if "python" in languages:
        f1, n1 = analyze_python(project, idx, settings, ctx, progress)
        findings += f1
        notes.update(n1)
    js_langs = tuple(l for l in ("javascript", "typescript") if l in languages)
    if js_langs:
        f2, n2 = analyze_js(project, idx, settings, ctx, progress, js_langs)
        findings += f2
        notes.update(n2)
    progress(78, "Checking files, assets and duplicates")
    f3, _ = analyze_files(project, idx, settings, ctx, progress)
    findings += f3

    th = S.effective_thresholds(settings)
    findings = [f for f in findings if f.confidence >= th["min_confidence"] and (f.certainty == "confirmed" or not th["confirmed_only"])]
    findings = _drop_nested(findings)
    dup_files = {f.file for f in findings if f.category == "duplicate_file"}
    findings = [f for f in findings if not (f.category == "unused_module" and f.file in dup_files)]
    # de-duplicate identical (category,file,line,symbol)
    seen, uniq = set(), []
    for f in findings:
        k = (f.category, f.file, f.line, f.symbol, f.plan.get("start"), tuple(f.plan.get("remove", [])))
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    findings = uniq

    progress(88, "Writing explanations")
    ctxn = settings.get("ui.context_lines", 3)
    cache = {}
    from ..util import sha256_file

    for f in findings:
        if f.item_type == "code":
            if f.file not in cache:
                txt = read_text(os.path.join(root, f.file), 4 * 1024 * 1024)
                cache[f.file] = (split_lines(txt) if txt is not None else [], sha256_file(os.path.join(root, f.file)))
            lines, sha = cache[f.file]
            f.file_sha = sha
        else:
            lines = []
            p = os.path.join(root, f.file)
            f.file_sha = sha256_file(p) if f.item_type == "file" and os.path.isfile(p) else ""
        f.extra["details"] = build_details(f, lines, ctxn)
        f.extra["fingerprint"] = fingerprint(f)

    red = redundant_bytes(findings, root)
    cats = Counter(f.category for f in findings)
    files_with = {f.file for f in findings if f.category in ("unused_function", "unused_class", "unused_export")}
    skipped_notes = [f"{k} ({v})" for k, v in notes.most_common(15)]
    unparsed = [f"{r}: {m}" for r, m in idx.syntax_errors]
    summary = {
        "languages": {k: {"loc": v, "files": len(idx.files_by_lang.get(k, []))} for k, v in idx.loc.items() if k != "markup"},
        "files_scanned": len(project.files),
        "skipped_dirs": project.skipped_dirs,
        "notes": skipped_notes + project.notes[:20],
        "syntax_errors": unparsed[:20],
        "dynamic_features": [f"{f} in {r} ({c}x)" for f, r, c in (idx.dynamic_py + idx.dynamic_js)[:10]],
        "limitations": LIMITATIONS,
        "categories": dict(cats),
        "thresholds": th,
        "settings_used": {k: settings.get(k) for k in ("scan.sensitivity", "scan.min_confidence", "scan.languages")},
    }
    return {"findings": findings, "summary": summary, "total_bytes": project.total_bytes, "redundant_bytes": red,
            "total_loc": sum(v for k, v in idx.loc.items() if k != "markup"), "total_files": len(project.files),
            "module_count": len(files_with), "n_findings": len(findings)}
