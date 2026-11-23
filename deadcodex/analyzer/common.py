"""Shared types and helpers for the analyzers."""
from __future__ import annotations

import hashlib
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

CATEGORY_LABELS = {
    "unused_function": "Unused Function",
    "unused_class": "Unused Class",
    "unused_import": "Unused Import",
    "unused_variable": "Zombie Variable",
    "unused_export": "Unused Export",
    "unreachable_code": "Unreachable Code",
    "dead_branch": "Dead Branch",
    "duplicate_code": "Duplicated Code",
    "duplicate_file": "Duplicate File",
    "junk_file": "Cache / Temp File",
    "vendor_dir": "Bundled Dependencies",
    "unused_asset": "Unreferenced Asset",
    "unused_module": "Unreferenced Module",
}

PY_EXTS = {".py"}
JS_EXTS = {".js", ".jsx", ".mjs", ".cjs"}
TS_EXTS = {".ts", ".tsx"}
LANG_BY_EXT = {**{e: "python" for e in PY_EXTS}, **{e: "javascript" for e in JS_EXTS}, **{e: "typescript" for e in TS_EXTS}}

# Text files whose *words* count as references to code symbols (templates, config, markup...).
OTHER_CODE_TEXT_EXTS = {".html", ".htm", ".jinja", ".jinja2", ".j2", ".njk", ".ejs", ".hbs", ".vue", ".svelte", ".php", ".rb", ".go",
                        ".java", ".kt", ".cs", ".json", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".conf", ".sh", ".bat", ".ps1",
                        ".xml", ".css", ".scss", ".less", ".env", ".mjml", ".txt.j2"}
DOC_TEXT_EXTS = {".md", ".rst", ".txt", ".adoc"}  # count as *file* references only, not symbol usage
SPECIAL_TEXT_NAMES = {"dockerfile", "procfile", "makefile", "jenkinsfile", "vagrantfile", "requirements.txt", "manifest.in"}
ASSET_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".ico", ".bmp", ".tif", ".tiff",
              ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".wav", ".ogg", ".mp4", ".webm", ".mov"}
ARCHIVE_EXTS = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".rar", ".7z"}
JUNK_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".ipynb_checkpoints", "htmlcov", ".nyc_output"}
VENDOR_DIR_NAMES = {"node_modules", "bower_components", "site-packages"}
ALWAYS_SKIP_DIRS = {".git", ".hg", ".svn"}
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_TEXT_BYTES = 1024 * 1024
PROTECTED_ASSET_NAMES = ("favicon", "apple-touch-icon", "robots", "og-image", "og_image", "logo192", "logo512", "android-chrome", "mstile", "safari-pinned")


@dataclass
class RawFinding:
    category: str
    file: str
    line: int
    end_line: int
    certainty: str  # confirmed | potential
    confidence: int
    language: str = ""
    symbol: str = ""
    title: str = ""
    severity: str = "Low"
    fix_mode: str = "manual"  # auto | review | manual
    item_type: str = "code"  # code | file | dir
    size_bytes: int = 0
    snippet: str = ""
    evidence: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    plan: dict = field(default_factory=dict)
    file_sha: str = ""


@dataclass
class PFile:
    rel: str
    abs: str
    size: int
    ext: str
    name: str

    @property
    def lang(self):
        return LANG_BY_EXT.get(self.ext)


@dataclass
class Project:
    root: Path
    files: list
    flagged_dirs: list  # (rel, abs, kind, size)
    skipped_dirs: dict  # name -> {"count": n, "size": bytes}
    notes: list = field(default_factory=list)
    total_bytes: int = 0

    def by_rel(self):
        return {f.rel: f for f in self.files}


def _is_venv(path: str) -> bool:
    return os.path.exists(os.path.join(path, "pyvenv.cfg"))


def dir_size_count(path: str):
    total = n = 0
    for r, _d, fs in os.walk(path):
        for f in fs:
            fp = os.path.join(r, f)
            try:
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
                    n += 1
            except OSError:
                pass
    return total, n


def discover(root, settings: dict) -> Project:
    """Walk the project (never following symlinks, never reading outside `root`)."""
    root = Path(root)
    exclude = set(settings.get("scan.exclude_dirs", []))
    files, flagged, skipped = [], [], {}
    total = 0
    for cur, dirs, fnames in os.walk(root, followlinks=False):
        keep = []
        for d in sorted(dirs):
            full = os.path.join(cur, d)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if os.path.islink(full):
                continue
            if d in ALWAYS_SKIP_DIRS:
                size, n = dir_size_count(full)
                total += size
                skipped.setdefault(d, {"count": 0, "size": 0})
                skipped[d]["count"] += n
                skipped[d]["size"] += size
                continue
            if d in JUNK_DIRS or d.endswith(".egg-info"):
                size, n = dir_size_count(full)
                total += size
                flagged.append((rel, full, "cache", size))
                continue
            if d in VENDOR_DIR_NAMES or _is_venv(full):
                size, n = dir_size_count(full)
                total += size
                flagged.append((rel, full, "vendor", size))
                continue
            if d in exclude:
                size, n = dir_size_count(full)
                total += size
                skipped.setdefault(d, {"count": 0, "size": 0})
                skipped[d]["count"] += n
                skipped[d]["size"] += size
                continue
            keep.append(d)
        dirs[:] = keep
        for f in sorted(fnames):
            fp = os.path.join(cur, f)
            if os.path.islink(fp):
                continue
            try:
                size = os.path.getsize(fp)
            except OSError:
                continue
            rel = os.path.relpath(fp, root).replace(os.sep, "/")
            total += size
            files.append(PFile(rel=rel, abs=fp, size=size, ext=os.path.splitext(f)[1].lower(), name=f))
    return Project(root=root, files=files, flagged_dirs=flagged, skipped_dirs=skipped, total_bytes=total)


def read_text(path, limit=MAX_TEXT_BYTES):
    """Return decoded text or None (binary / too large)."""
    try:
        if os.path.getsize(path) > limit:
            return None
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    if b"\x00" in raw[:4096]:
        return None
    text = raw.decode("utf-8", errors="replace")
    return text[1:] if text.startswith("\ufeff") else text


def split_lines(text: str) -> list:
    """Split on '\\n' only, keeping line endings, so line numbers match `ast` and the JS scanner."""
    parts = text.split("\n")
    out = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        out.append(parts[-1])
    return out


def sha256_bytes_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def numbered(lines, start, end, limit=40):
    out = []
    for n in range(start, min(end, start + limit - 1) + 1):
        out.append(f"{n:>4} | {lines[n - 1].rstrip(chr(10))}")
    if end - start + 1 > limit:
        out.append(f"     | ... ({end - start + 1 - limit} more lines)")
    return "\n".join(out)


def range_bytes(lines, start, end):
    return sum(len(l.encode("utf-8", "replace")) for l in lines[start - 1:end])


def severity_for(category: str, size_bytes: int = 0, nlines: int = 0, certainty: str = "potential") -> str:
    if category in ("unused_function", "unused_class", "unused_export", "unused_module", "dead_branch", "duplicate_code"):
        return "High" if nlines >= 30 else "Medium" if nlines >= 8 or category == "unused_module" else "Low"
    if category == "unreachable_code":
        return "Medium" if nlines >= 3 else "Low"
    if category == "unused_import":
        return "Low"
    if category == "unused_variable":
        return "Low"
    if category in ("junk_file", "duplicate_file", "unused_asset", "vendor_dir"):
        if size_bytes >= 5 * 1024 * 1024:
            return "High"
        if size_bytes >= 100 * 1024:
            return "Medium"
        return "Low"
    return "Low"


def stdlib_names():
    import sys

    names = getattr(sys, "stdlib_module_names", None)
    if names:
        return set(names)
    return set(("abc argparse array ast asyncio base64 binascii bisect builtins calendar cgi codecs collections concurrent configparser "
                "contextlib copy csv ctypes dataclasses datetime decimal difflib email enum errno fnmatch fractions functools gc getpass "
                "glob gzip hashlib heapq hmac html http importlib inspect io ipaddress itertools json logging math mimetypes multiprocessing "
                "numbers operator os pathlib pickle platform pprint queue random re secrets select shlex shutil signal smtplib socket "
                "sqlite3 ssl stat statistics string struct subprocess sys tempfile textwrap threading time timeit tkinter token tokenize "
                "traceback types typing unicodedata unittest urllib uuid warnings weakref xml zipfile zlib __future__").split())
