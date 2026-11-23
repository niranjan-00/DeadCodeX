"""File-level analysis: cache/temp files, bundled dependency folders, duplicate files, unreferenced
assets and modules, and duplicated code blocks."""
from __future__ import annotations

import os
import re
from collections import defaultdict

from .common import (ARCHIVE_EXTS, ASSET_EXTS, JS_EXTS, PROTECTED_ASSET_NAMES, TS_EXTS, RawFinding, Project, read_text, severity_for,
                     sha256_bytes_of, split_lines)
from .index import ProjectIndex
from .js_an import is_entry_like, is_test_js
from .python_an import CONFIG_FILE_STEMS, is_test_file

JUNK_NAMES = {".ds_store": 98, "thumbs.db": 98, "desktop.ini": 95, ".coverage": 85}
JUNK_EXT = {".pyc": 98, ".pyo": 98, ".swp": 92, ".swo": 92, ".tmp": 88, ".temp": 88, ".orig": 80, ".rej": 80, ".bak": 72, ".log": 72, ".old": 60}
PY_ENTRY_STEMS = {"__init__", "__main__", "setup", "conftest", "manage", "wsgi", "asgi", "app", "main", "run", "cli", "server", "settings", "config", "fabfile", "noxfile", "tasks"}


def _file_finding(category, pf, conf, certainty, mode, title, evidence, extra, lang="", item_type="file", size=None):
    f = RawFinding(category=category, file=pf if isinstance(pf, str) else pf.rel, line=0, end_line=0, certainty=certainty,
                   confidence=int(max(5, min(99, conf))), language=lang, symbol=os.path.basename(pf if isinstance(pf, str) else pf.rel),
                   title=title, fix_mode=mode, item_type=item_type, size_bytes=size if size is not None else pf.size,
                   evidence=evidence, extra=extra)
    f.plan = {"op": "delete_path", "path": f.file, "is_dir": item_type == "dir"} if mode != "manual" else {}
    f.severity = severity_for(category, f.size_bytes)
    return f


def _path_referenced(rel: str, idx: ProjectIndex) -> bool:
    low = rel.lower()
    base = low.rsplit("/", 1)[-1]
    if base in idx.ref_basenames:
        return True
    parts = low.split("/")
    for i in range(len(parts) - 1):
        if "/".join(parts[i:]) in idx.ref_paths:
            return True
    return False


def _py_module_referenced(rel: str, idx: ProjectIndex, has_main: bool) -> bool:
    if has_main:
        return True
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    for i in range(len(parts)):
        if ".".join(parts[i:]) in idx.imports_py:
            return True
    stem = parts[-1] if parts else ""
    if idx.other_words[stem] > 0:
        return True
    return rel.rsplit("/", 1)[-1].lower() in idx.ref_basenames


def _js_resolved_targets(idx: ProjectIndex):
    resolved, alias = set(), set()
    exts = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".json")
    import posixpath

    for importer, spec in idx.js_specs:
        if spec.startswith("."):
            base = posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec))
            resolved.add(base)
            for e in exts:
                resolved.add(base + e)
                resolved.add(f"{base}/index{e}")
        else:
            s = re.sub(r"^(?:@/|~/|#/?)", "", spec)
            s = re.sub(r"^src/", "", s)
            alias.add(os.path.splitext(s)[0] if s.endswith(exts) else s)
    return resolved, alias


def analyze_files(project: Project, idx: ProjectIndex, settings: dict, ctx: dict, progress=None):
    findings = []
    notes = []
    root = project.root
    names_here = {f.rel for f in project.files}

    # ---------------------------------------------------------- bundled / cache directories
    if settings.get("scan.detect_junk", True):
        for rel, absd, kind, size in project.flagged_dirs:
            base = os.path.basename(rel)
            parent = os.path.dirname(rel)
            if kind == "cache":
                ev = [f"`{base}` is a tool-generated cache/output directory ({size} bytes). It is recreated automatically the next time the tool runs.",
                      "It contains no hand-written source code."]
                findings.append(_file_finding("junk_file", rel, 98, "confirmed", "auto", f"Cache directory '{base}/'", ev,
                                              {"kind": "cache_dir", "dir": True}, item_type="dir", size=size))
            else:
                parent_has = lambda n: os.path.exists(os.path.join(root, parent, n)) if parent else os.path.exists(os.path.join(root, n))
                if base == "node_modules" or base == "bower_components":
                    manifest = parent_has("package.json")
                    lock = parent_has("package-lock.json") or parent_has("yarn.lock") or parent_has("pnpm-lock.yaml")
                    conf = 88 if manifest else 40
                    ev = [f"`{rel}/` holds installed npm packages ({size} bytes).",
                          ("package.json found next to it, so `npm install` can recreate it" + (" (a lock file pins exact versions)." if lock else "."))
                          if manifest else "No package.json found next to it, so the packages may not be reproducible."]
                else:
                    manifest = any(parent_has(n) for n in ("requirements.txt", "pyproject.toml", "Pipfile", "setup.py", "setup.cfg"))
                    conf = 88 if manifest else 55
                    ev = [f"`{rel}/` is a Python virtual environment / site-packages folder ({size} bytes).",
                          "A dependency manifest exists next to it, so it can be recreated." if manifest else "No requirements/pyproject file found next to it, so the dependency list may be lost."]
                findings.append(_file_finding("vendor_dir", rel, conf, "confirmed" if conf >= 85 else "potential", "review",
                                              f"Bundled dependencies '{rel}/'", ev, {"kind": "vendor_dir", "dir": True, "manifest": manifest},
                                              item_type="dir", size=size))
        # junk files
        for pf in project.files:
            low = pf.name.lower()
            conf = JUNK_NAMES.get(low)
            if conf is None and pf.name.endswith("~"):
                conf = 90
            if conf is None:
                conf = JUNK_EXT.get(pf.ext)
            if conf is None and pf.ext in ARCHIVE_EXTS and pf.size >= 1024 * 1024:
                conf = 45
            if conf is None:
                continue
            ev = []
            if pf.ext in ARCHIVE_EXTS:
                ev.append(f"A {pf.size} byte archive file is stored inside the project. Archives usually are copies of other content, not source.")
                kind = "archive"
            else:
                ev.append(f"The file name matches a generated/temporary/backup pattern ('{pf.ext or pf.name}').")
                kind = "temp"
            if _path_referenced(pf.rel, idx):
                conf -= 20
                ev.append("Its name is mentioned somewhere in the project (a configuration may refer to it) - check before removing.")
            else:
                ev.append("Its name is not mentioned in any source, template or configuration file.")
            certainty = "confirmed" if conf >= 90 else "potential"
            mode = "auto" if conf >= 90 else "review"
            findings.append(_file_finding("junk_file", pf, conf, certainty, mode, f"Temporary/generated file '{pf.name}'" if kind == "temp" else f"Bundled archive '{pf.name}'",
                                          ev, {"kind": kind}))

    # ---------------------------------------------------------- unreferenced assets + modules
    if settings.get("scan.detect_assets", True):
        has_code = bool(idx.n_code_files)
        dyn_strings = idx.string_dirs_dynamic
        for pf in project.files:
            if pf.ext not in ASSET_EXTS or not has_code:
                continue
            low = pf.name.lower()
            if any(low.startswith(p) for p in PROTECTED_ASSET_NAMES):
                continue
            if _path_referenced(pf.rel, idx):
                continue
            stem = pf.name.rsplit(".", 1)[0]
            if stem.lower() in idx.ref_basenames or (len(stem) > 3 and stem in idx.all_words):
                continue
            conf = 80
            ev = [f"The file name `{pf.name}` does not appear in any of the {idx.n_code_files + idx.n_other_files} source, template, style or documentation files searched.",
                  "No import/require/url()/src= reference to it was found."]
            parent = os.path.basename(os.path.dirname(pf.rel))
            dyn = [d for d in dyn_strings if parent and parent.lower() in d[1].lower()]
            if dyn:
                conf -= 35
                ev.append(f"{dyn[0][0]} builds file paths dynamically (\"{dyn[0][1][:60]}\"), so this asset might be loaded by a computed name.")
            top = pf.rel.split("/")[0].lower()
            if top in ("static", "public", "assets", "www", "wwwroot", "media"):
                conf -= 10
                ev.append("It lives in a public/static folder; web pages outside this project could link to it directly.")
            conf = max(15, conf)
            findings.append(_file_finding("unused_asset", pf, conf, "confirmed" if conf >= 80 else "potential", "review", f"Unreferenced asset '{pf.name}'",
                                          ev, {"kind": "asset"}))
        # python modules
        py_files = [f for f in project.files if f.ext == ".py"]
        if len(py_files) > 1:
            for pf in py_files:
                stem = pf.name[:-3]
                if stem in PY_ENTRY_STEMS or is_test_file(pf.rel) or stem in CONFIG_FILE_STEMS:
                    continue
                text = read_text(pf.abs) or ""
                has_main = bool(re.search(r"""if\s+__name__\s*==\s*['"]__main__['"]""", text))
                if _py_module_referenced(pf.rel, idx, has_main):
                    continue
                if pf.size == 0:
                    continue
                ev = [f"No `import`/`from ... import` in any of the {idx.n_code_files} source files resolves to module `{pf.rel[:-3].replace('/', '.')}`.",
                      "Its file name is not mentioned in any other text file (Dockerfile, Procfile, config, scripts).",
                      "It has no `if __name__ == '__main__'` block, so it is not a runnable script."]
                conf = 55
                if idx.dynamic_py:
                    conf -= 15
                    ev.append(f"The project uses {idx.dynamic_py[0][0]} in {idx.dynamic_py[0][1]}, which can import modules by computed name.")
                findings.append(_file_finding("unused_module", pf, conf, "potential", "review", f"Unreferenced module '{pf.rel}'", ev,
                                              {"kind": "module", "module": pf.rel[:-3].replace("/", ".")}, lang="python"))
        # js modules
        js_files = [f for f in project.files if f.lang in ("javascript", "typescript") and not f.name.endswith(".d.ts")]
        if len(js_files) > 1:
            resolved, alias = _js_resolved_targets(idx)
            for pf in js_files:
                if is_entry_like(pf.rel) or is_test_js(pf.rel):
                    continue
                noext = os.path.splitext(pf.rel)[0]
                if pf.rel in resolved or noext in resolved:
                    continue
                parts = noext.split("/")
                if any("/".join(parts[i:]) in alias for i in range(len(parts))):
                    continue
                if pf.name.lower() in idx.ref_basenames:
                    continue
                if pf.size == 0:
                    continue
                ev = [f"No import/require/dynamic import in the {idx.n_code_files} source files resolves to `{pf.rel}`.",
                      f"The file name `{pf.name}` is not mentioned in HTML, package.json or any other text file."]
                conf = 55
                if idx.dynamic_js:
                    conf -= 15
                    ev.append(f"The project uses {idx.dynamic_js[0][0]} in {idx.dynamic_js[0][1]}, which can load modules by computed name.")
                findings.append(_file_finding("unused_module", pf, conf, "potential", "review", f"Unreferenced module '{pf.rel}'", ev,
                                              {"kind": "module"}, lang=pf.lang))

    # ---------------------------------------------------------- duplicate files
    if settings.get("scan.detect_duplicates", True):
        by_size = defaultdict(list)
        for pf in project.files:
            if pf.size >= 64:
                by_size[pf.size].append(pf)
        for size, group in by_size.items():
            if len(group) < 2:
                continue
            by_hash = defaultdict(list)
            for pf in group:
                try:
                    by_hash[sha256_bytes_of(pf.abs)].append(pf)
                except OSError:
                    pass
            for h, same in by_hash.items():
                if len(same) < 2:
                    continue
                same.sort(key=lambda f: (f.rel.count("/"), len(f.rel), f.rel))
                keep = same[0]
                for dup in same[1:]:
                    referenced = _path_referenced(dup.rel, idx)
                    if dup.ext == ".py" and not referenced:
                        referenced = _py_module_referenced(dup.rel, idx, False)
                    conf = 55 if referenced else 85
                    ev = [f"Byte-for-byte identical (SHA-256 {h[:12]}...) to `{keep.rel}`.",
                          (f"The file name `{dup.name}` is referenced somewhere in the project, so removing it could break that reference." if referenced
                           else f"The file name `{dup.name}` is not referenced by any file searched.")]
                    findings.append(_file_finding("duplicate_file", dup, conf, "confirmed" if conf >= 85 else "potential", "auto" if conf >= 85 else "review",
                                                  f"Duplicate of '{keep.rel}'", ev, {"kind": "duplicate", "original": keep.rel, "sha": h[:12]},
                                                  lang=dup.lang or ""))
        # ---- duplicated code blocks (informational, never auto-removed)
        findings.extend(_duplicate_code(project, idx))
    return findings, notes


# ------------------------------------------------------------------ duplicated code blocks
_SKIP_PREFIX = ("#", "//", "/*", "*", "import ", "from ", "export {", "export *", "@")
_TRIVIAL = {"{", "}", "});", "})", ");", "]", "],", "};", "else:", "else {", "} else {", "try:", "finally:", "pass", "break;", "continue;", "return;", "end"}


def _duplicate_code(project, idx, K=8, MIN_CHARS=240):
    per_file = {}
    for pf in project.files:
        if pf.lang not in ("python", "javascript", "typescript") or pf.name.endswith(".d.ts") or pf.size > 1024 * 1024:
            continue
        text = read_text(pf.abs)
        if text is None:
            continue
        lines = split_lines(text)
        items = []
        for n, l in enumerate(lines, 1):
            s = re.sub(r"\s+", " ", l.strip())
            if len(s) < 4 or s.startswith(_SKIP_PREFIX) or s in _TRIVIAL or not re.search(r"[A-Za-z0-9]", s):
                continue
            items.append((n, hash(s), len(s)))
        if len(items) >= K:
            per_file[pf.rel] = (items, lines, pf.lang)
    windows = defaultdict(list)
    for rel, (items, _l, _g) in per_file.items():
        hs = [h for _, h, _ in items]
        for i in range(len(hs) - K + 1):
            windows[hash(tuple(hs[i:i + K]))].append((rel, i))
    covered = defaultdict(dict)  # rel -> {item_index: window_key}
    for key, occ in windows.items():
        if len(occ) < 2 or len(occ) > 8:
            continue
        # ignore windows whose occurrences all overlap within the same file
        spread = {(rel, i // K) for rel, i in occ}
        if len(spread) < 2:
            continue
        for rel, i in occ:
            for j in range(i, i + K):
                covered[rel].setdefault(j, key)
    results = []
    for rel, cov in covered.items():
        items, lines, lang = per_file[rel]
        idxs = sorted(cov)
        runs, cur = [], [idxs[0]]
        for j in idxs[1:]:
            if j == cur[-1] + 1:
                cur.append(j)
            else:
                runs.append(cur)
                cur = [j]
        runs.append(cur)
        for run in runs:
            start_l, end_l = items[run[0]][0], items[run[-1]][0]
            chars = sum(items[j][2] for j in run)
            if len(run) < K or chars < MIN_CHARS:
                continue
            key = cov[run[0]]
            others = [(r, items_o[i][0]) for r, i in windows[key] if r != rel or abs(items_o_start(per_file, r, i) - start_l) >= K
                      for items_o in [per_file[r][0]]]
            others = [o for o in others if o != (rel, start_l)][:3]
            results.append((chars, rel, start_l, end_l, lang, others, lines))
    results.sort(key=lambda r: -r[0])
    out = []
    for chars, rel, s, e, lang, others, lines in results[:40]:
        from .common import numbered, range_bytes

        loc = ", ".join(f"{r}:{ln}" for r, ln in others) or "another location"
        ev = [f"These {e - s + 1} lines (about {chars} characters of code, ignoring blank lines, comments and whitespace) also appear at {loc}.",
              "Matching is on normalised lines (whitespace collapsed), so renamed variables are NOT detected - this is a conservative, exact-copy check."]
        f = RawFinding(category="duplicate_code", file=rel, line=s, end_line=e, certainty="potential", confidence=60, language=lang,
                       symbol=f"{rel}:{s}-{e}", title=f"Duplicated block ({e - s + 1} lines)", fix_mode="manual", item_type="code",
                       size_bytes=range_bytes(lines, s, e), snippet=numbered(lines, s, e, 14), evidence=ev,
                       extra={"others": [f"{r}:{ln}" for r, ln in others], "lines": e - s + 1})
        f.severity = severity_for("duplicate_code", f.size_bytes, e - s + 1)
        out.append(f)
    return out


def items_o_start(per_file, rel, i):
    return per_file[rel][0][i][0]
