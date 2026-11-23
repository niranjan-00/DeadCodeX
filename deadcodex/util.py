"""Small shared helpers (time, hashing, formatting, safe paths)."""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path


def utcnow() -> datetime:
    """Naive UTC 'now' (compatible with the naive datetimes already stored in the DB)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def sha256_file(path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def human_size(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}" if n < 100 else f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def timeago(dt) -> str:
    if not dt:
        return "never"
    secs = int((utcnow() - dt).total_seconds())
    if secs < 5:
        return "just now"
    if secs < 60:
        return f"{secs} seconds ago"
    if secs < 3600:
        m = secs // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if secs < 86400:
        h = secs // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = secs // 86400
    return f"{d} day{'s' if d != 1 else ''} ago"


def to_posix(rel: str) -> str:
    return rel.replace("\\", "/")


def safe_join(base, rel: str) -> Path:
    """Join `rel` under `base`, refusing anything that escapes `base` (raises ValueError)."""
    base_p = Path(os.path.realpath(base))
    target = Path(os.path.realpath(base_p / rel))
    if target != base_p and base_p not in target.parents:
        raise ValueError("path escapes project directory")
    return target


_NAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


def clean_display_name(name: str, limit: int = 100) -> str:
    name = _NAME_RE.sub("", (name or "").strip())
    return name[:limit].strip()


def dir_size(path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
            except OSError:
                pass
    return total
