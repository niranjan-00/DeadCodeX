"""Safe ZIP validation and extraction.

Defences: ZIP-Slip / path traversal, absolute and drive-letter paths, symlinks and special files,
encrypted entries, duplicate entries, decompression bombs (header sizes *and* real streamed bytes),
file-count and size limits. Nothing in the archive is ever executed.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SOURCE_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
IGNORED_TOP = {"__MACOSX", ".DS_Store", "Thumbs.db"}
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_CTRL = re.compile(r"[\x00-\x1f]")


class ArchiveError(Exception):
    """Raised with a message that is safe and useful to show to the user."""


@dataclass
class Limits:
    max_archive_bytes: int = 50 * 1024 * 1024
    max_extracted_bytes: int = 500 * 1024 * 1024
    max_files: int = 20000
    max_ratio: int = 200  # total uncompressed / compressed, only enforced above `ratio_floor`
    ratio_floor: int = 100 * 1024 * 1024
    max_entry_ratio: int = 1000
    max_depth: int = 40


@dataclass
class ExtractResult:
    root: Path
    file_count: int
    total_bytes: int
    source_files: int


def _normalise(name: str) -> str:
    return name.replace("\\", "/")


def _check_name(raw: str) -> str:
    name = _normalise(raw)
    if _CTRL.search(name):
        raise ArchiveError(f"Unsafe archive: entry name contains control characters ({raw!r}).")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise ArchiveError(f"Unsafe archive: absolute path in entry '{raw}'.")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ArchiveError(f"Unsafe archive: path traversal ('..') in entry '{raw}'.")
    for p in parts:
        if p.endswith((" ", ".")):
            raise ArchiveError(f"Unsafe archive: entry '{raw}' has a name that is invalid on Windows.")
        if os.name == "nt" and p.split(".")[0].upper() in _WIN_RESERVED:
            raise ArchiveError(f"Unsafe archive: reserved file name in entry '{raw}'.")
    return "/".join(parts)


def inspect_zip(zip_path, limits: Limits) -> list:
    """Validate the archive *without extracting*. Returns [(ZipInfo, clean_name)] for file entries."""
    zip_path = Path(zip_path)
    size = zip_path.stat().st_size
    if size == 0:
        raise ArchiveError("The uploaded file is empty.")
    if size > limits.max_archive_bytes:
        raise ArchiveError(f"Archive is {size / 1048576:.1f} MB; the limit is {limits.max_archive_bytes / 1048576:.0f} MB.")
    if not zipfile.is_zipfile(zip_path):
        raise ArchiveError("This is not a valid ZIP archive (corrupt file or wrong format).")
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ArchiveError(f"The ZIP archive is corrupt: {exc}")
    entries, seen, total = [], set(), 0
    with zf:
        infos = zf.infolist()
        if len(infos) > limits.max_files + 5000:  # directory entries are cheap; files are limited below
            raise ArchiveError(f"Archive has too many entries ({len(infos)}).")
        for zi in infos:
            clean = _check_name(zi.filename)
            if not clean:
                continue
            if clean.split("/")[0] in IGNORED_TOP:
                continue
            if clean.count("/") > limits.max_depth:
                raise ArchiveError("Unsafe archive: directory nesting is unreasonably deep.")
            mode = (zi.external_attr >> 16) & 0xFFFF
            if mode and stat.S_ISLNK(mode):
                raise ArchiveError(f"Unsafe archive: symbolic link '{zi.filename}' is not allowed.")
            if mode and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)) and stat.S_IFMT(mode):
                raise ArchiveError(f"Unsafe archive: special file '{zi.filename}' is not allowed.")
            if zi.flag_bits & 0x1:
                raise ArchiveError("The archive contains encrypted entries, which cannot be analysed.")
            if zi.is_dir():
                continue
            key = clean.lower()
            if key in seen:
                raise ArchiveError(f"Unsafe archive: duplicate entry '{clean}'.")
            seen.add(key)
            if zi.compress_size > 0 and zi.file_size / zi.compress_size > limits.max_entry_ratio and zi.file_size > 10 * 1024 * 1024:
                raise ArchiveError(f"Unsafe archive: entry '{clean}' has a suspicious compression ratio (possible decompression bomb).")
            total += zi.file_size
            entries.append((zi, clean))
            if len(entries) > limits.max_files:
                raise ArchiveError(f"Archive contains more than {limits.max_files} files; the limit is {limits.max_files}.")
        if total > limits.max_extracted_bytes:
            raise ArchiveError(f"Archive would expand to {total / 1048576:.0f} MB; the limit is {limits.max_extracted_bytes / 1048576:.0f} MB.")
        if total > limits.ratio_floor and size and total / size > limits.max_ratio:
            raise ArchiveError("Unsafe archive: overall compression ratio is suspicious (possible decompression bomb).")
    if not entries:
        raise ArchiveError("The archive contains no files.")
    return entries


def extract_zip(zip_path, dest, limits: Limits) -> ExtractResult:
    """Validate then extract into the *empty* directory `dest`; detect and return the project root."""
    entries = inspect_zip(zip_path, limits)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.iterdir()):
        raise ArchiveError("Internal error: extraction directory is not empty.")
    dest_real = os.path.realpath(dest)
    written_total = 0
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for zi, clean in entries:
                target = os.path.realpath(os.path.join(dest_real, clean))
                if os.path.commonpath([dest_real, target]) != dest_real or target == dest_real:
                    raise ArchiveError(f"Unsafe archive: entry '{zi.filename}' escapes the project directory.")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                declared = zi.file_size
                written = 0
                try:
                    with zf.open(zi) as src, open(target, "wb") as out:
                        while True:
                            chunk = src.read(1024 * 256)
                            if not chunk:
                                break
                            written += len(chunk)
                            written_total += len(chunk)
                            # Do not trust header sizes: enforce on bytes actually produced.
                            if written > declared + 1024 or written_total > limits.max_extracted_bytes:
                                raise ArchiveError("Unsafe archive: contents are larger than declared (possible decompression bomb).")
                            out.write(chunk)
                except zipfile.BadZipFile as exc:
                    raise ArchiveError(f"The ZIP archive is corrupt ({clean}): {exc}")
                except (RuntimeError, NotImplementedError) as exc:
                    raise ArchiveError(f"Unsupported ZIP feature in '{clean}': {exc}")
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    root = detect_root(dest)
    files, total, src_files = 0, 0, 0
    for r, _d, fs in os.walk(root):
        for f in fs:
            files += 1
            total += os.path.getsize(os.path.join(r, f))
            if Path(f).suffix.lower() in SOURCE_EXTS:
                src_files += 1
    return ExtractResult(root=root, file_count=files, total_bytes=total, source_files=src_files)


def detect_root(extracted: Path) -> Path:
    """If the archive wraps everything in a single folder (possibly nested), descend into it."""
    root = Path(extracted)
    for _ in range(5):
        children = [c for c in root.iterdir() if c.name not in IGNORED_TOP]
        if len(children) == 1 and children[0].is_dir() and not children[0].is_symlink():
            root = children[0]
        else:
            break
    return root


def resolve_subdir(root: Path, subdir: str) -> Path:
    subdir = (subdir or "").strip().strip("/\\")
    if not subdir:
        return root
    clean = _check_name(subdir)
    target = Path(os.path.realpath(root / clean))
    root_real = Path(os.path.realpath(root))
    if root_real not in target.parents or not target.is_dir():
        raise ArchiveError(f"Subdirectory '{subdir}' was not found in the project.")
    return target


def promote_root(root: Path, final_dir: Path):
    """Move the detected project root to `final_dir` (which must not exist) and clean leftovers."""
    final_dir = Path(final_dir)
    top = final_dir.parent / "_extract"
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(root), str(final_dir))
    shutil.rmtree(top, ignore_errors=True)
