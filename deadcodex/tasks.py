"""Background work: import (ZIP/GitHub), analysis, cleanup runs, retention. Each task opens its own app context."""
from __future__ import annotations

import json
import logging
import shutil
import threading
import traceback
from pathlib import Path

from flask import current_app

from . import archive, github, settings_schema as S, store
from .analyzer.engine import run_analysis
from .extensions import db
from .models import CleanupRun, Finding, Scan
from .util import sha256_file, utcnow

log = logging.getLogger("deadcodex.tasks")


def submit(app, fn, *args):
    if app.config.get("TASKS_SYNC"):
        fn(app, *args)
        return None
    t = threading.Thread(target=fn, args=(app, *args), daemon=True, name=f"dcx-{fn.__name__}")
    t.start()
    return t


def recover_interrupted():
    """After a restart no task can still be running: mark unfinished work as failed instead of leaving it spinning."""
    for scan in Scan.query.filter(Scan.status.in_(["Importing", "Processing", "Pending"])).all():
        scan.status = "Failed"
        scan.error_message = "Interrupted by an application restart. Re-scan the project to try again."
    for run in CleanupRun.query.filter_by(status="Running").all():
        run.status = "Failed"
        run.finished_at = utcnow()
        run.log = (run.log or "") + "\n> Interrupted by an application restart. Files may be partially changed: use Rollback if available."
    db.session.commit()


def _progress(scan_id):
    state = {"last": -1}

    def cb(pct, msg):
        if pct == state["last"] and msg:
            return
        state["last"] = pct
        s = db.session.get(Scan, scan_id)
        if s:
            s.progress, s.progress_message = int(pct), msg[:290]
            db.session.commit()

    return cb


def _limits(settings) -> archive.Limits:
    return archive.Limits(max_archive_bytes=settings["upload.max_zip_mb"] * 1024 * 1024,
                          max_extracted_bytes=settings["upload.max_extracted_mb"] * 1024 * 1024,
                          max_files=settings["upload.max_files"])


def _fail(scan_id, message):
    db.session.rollback()
    s = db.session.get(Scan, scan_id)
    if s:
        s.status, s.error_message, s.finished_at = "Failed", message[:2000], utcnow()
        db.session.commit()


def prepare_source(scan, zip_path: Path, settings, subdir=None):
    """Extract `zip_path` into the workspace: source/ (pristine) and current/ (working copy)."""
    ws = store.workspace(scan)
    for d in ("source", "current", "_extract"):
        shutil.rmtree(ws / d, ignore_errors=True)
    result = archive.extract_zip(zip_path, ws / "_extract", _limits(settings))
    root = result.root
    if subdir:
        root = archive.resolve_subdir(root, subdir)
    if result.source_files == 0 and not any(p.suffix.lower() in archive.SOURCE_EXTS for p in root.rglob("*") if p.is_file()):
        shutil.rmtree(ws / "_extract", ignore_errors=True)
        raise archive.ArchiveError("No supported source files found (Python .py, JavaScript .js/.jsx/.mjs/.cjs, TypeScript .ts/.tsx). Nothing to analyze.")
    archive.promote_root(root, ws / "source")
    shutil.copytree(ws / "source", ws / "current", symlinks=False)
    return result


def zip_import_task(app, scan_id, settings):
    with app.app_context():
        try:
            scan = db.session.get(Scan, scan_id)
            cb = _progress(scan_id)
            cb(2, "Validating and extracting archive")
            ws = store.workspace(scan)
            prepare_source(scan, ws / "original.zip", settings, scan.subdir)
            scan.status = "Processing"
            db.session.commit()
            analyze_scan_inner(scan_id, settings)
        except archive.ArchiveError as e:
            _fail(scan_id, str(e))
        except Exception as e:  # pragma: no cover
            log.error("zip import failed: %s", traceback.format_exc())
            _fail(scan_id, f"Unexpected error while importing: {type(e).__name__}")


def github_import_task(app, scan_id, settings, token):
    with app.app_context():
        try:
            scan = db.session.get(Scan, scan_id)
            ref = github.parse_github_url(scan.source_url, scan.branch, scan.subdir)
            cb = _progress(scan_id)
            cb(2, "Contacting GitHub")
            ws = store.workspace(scan)
            meta = github.fetch_repository(ref, token, ws / "original.zip", settings["upload.max_zip_mb"] * 1024 * 1024)
            scan = db.session.get(Scan, scan_id)
            scan.branch, scan.commit_sha = meta["branch"], meta["commit_sha"]
            scan.archive_sha256 = sha256_file(ws / "original.zip")
            scan.status = "Processing"
            db.session.commit()
            cb(10, "Extracting repository")
            prepare_source(scan, ws / "original.zip", settings, scan.subdir)
            analyze_scan_inner(scan_id, settings)
        except (github.GitHubError, archive.ArchiveError) as e:
            _fail(scan_id, str(e))
        except Exception as e:  # pragma: no cover
            log.error("github import failed: %s", traceback.format_exc())
            _fail(scan_id, f"Unexpected error while importing: {type(e).__name__}")


def rescan_task(app, scan_id, settings):
    with app.app_context():
        try:
            analyze_scan_inner(scan_id, settings)
        except Exception as e:  # pragma: no cover
            log.error("scan failed: %s", traceback.format_exc())
            _fail(scan_id, f"Analysis failed: {type(e).__name__}: {e}")


def analyze_scan_inner(scan_id, settings):
    """Analyze workspace/current, replace findings (keeping approve/reject decisions) and update the Scan row."""
    scan = db.session.get(Scan, scan_id)
    scan.status, scan.error_message = "Processing", None
    db.session.commit()
    cb = _progress(scan_id)
    root = store.workspace(scan) / "current"
    result = run_analysis(root, settings, cb)
    old = {f.fingerprint: f.review_status for f in Finding.query.filter_by(scan_id=scan_id).all() if f.review_status != "pending"}
    Finding.query.filter_by(scan_id=scan_id).delete()
    for f in result["findings"]:
        fp = f.extra.get("fingerprint")
        db.session.add(Finding(
            scan_id=scan_id, fingerprint=fp, category=f.category, language=f.language, file=f.file, line=f.line, end_line=f.end_line,
            symbol=f.symbol, title=f.title, certainty=f.certainty, confidence=f.confidence, severity=f.severity, fix_mode=f.fix_mode,
            item_type=f.item_type, size_bytes=f.size_bytes, file_sha=f.file_sha, snippet=f.snippet,
            details=json.dumps(f.extra.get("details", {})), plan=json.dumps(f.plan), review_status=old.get(fp, "pending")))
    fs = result["findings"]
    scan = db.session.get(Scan, scan_id)
    scan.total_files = result["total_files"]
    scan.total_loc = result["total_loc"]
    scan.total_bytes = result["total_bytes"]
    scan.redundant_bytes = result["redundant_bytes"]
    scan.unused_functions = sum(1 for f in fs if f.category in ("unused_function", "unused_class", "unused_export"))
    scan.zombie_variables = sum(1 for f in fs if f.category == "unused_variable")
    scan.module_count = result["module_count"]
    scan.confirmed_count = sum(1 for f in fs if f.certainty == "confirmed")
    scan.potential_count = len(fs) - scan.confirmed_count
    scan.cleanup_percentage = round(100.0 * scan.redundant_bytes / scan.total_bytes, 1) if scan.total_bytes else 0.0
    scan.summary = json.dumps(result["summary"])
    scan.status, scan.progress, scan.progress_message, scan.finished_at = "Completed", 100, "Analysis complete", utcnow()
    db.session.commit()


def run_cleanup_task(app, run_id):
    with app.app_context():
        from . import cleanup

        cleanup.execute_run(run_id)


def purge_expired(user_id, days) -> int:
    """Delete this user's projects older than `days` (retention setting). Returns count."""
    if not days:
        return 0
    from datetime import timedelta

    cutoff = utcnow() - timedelta(days=days)
    n = 0
    for scan in Scan.query.filter(Scan.user_id == user_id, Scan.date < cutoff).all():
        delete_project(scan)
        n += 1
    return n


def delete_project(scan):
    try:
        ws = store.workspace(scan)
        shutil.rmtree(ws, ignore_errors=True)
    except FileNotFoundError:
        pass
    db.session.delete(scan)
    db.session.commit()
