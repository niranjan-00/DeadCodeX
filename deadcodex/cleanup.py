"""Cleanup / fix engine: plan -> preview -> backup -> apply -> validate -> (auto) rollback; history; cleaned ZIP.

Safety model
  * `source/` (pristine extraction) and `original.zip` are never modified.
  * Changes happen only in `current/`, after the affected files were copied to `backups/run_<id>/`.
  * Every changed file is re-validated (syntax parse; nothing is executed). A failure restores that file at once;
    an unexpected error restores the whole run.
  * Only findings that are fixable, confident enough (or explicitly approved), unchanged since the scan and
    not rejected are applied; everything else is reported with the reason it was skipped.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import zipfile
from collections import defaultdict
from pathlib import Path

from . import fixes, store
from .analyzer.common import split_lines
from .extensions import db
from .models import CleanupRun, Finding, Scan
from .util import dir_size, safe_join, sha256_file, utcnow

_locks = defaultdict(threading.Lock)


# ------------------------------------------------------------------ helpers
def _paths(scan):
    ws = store.workspace(scan)
    return ws, ws / "current", ws / "backups", ws / "outputs"


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="surrogateescape")


def _write_atomic(path: Path, text: str):
    tmp = path.with_name(path.name + ".dcx_tmp")
    tmp.write_bytes(text.encode("utf-8", errors="surrogateescape"))
    os.replace(tmp, path)


def _for_validation(text: str) -> str:
    t = text.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
    return t[1:] if t.startswith("﻿") else t


# ------------------------------------------------------------------ candidates (Cleanup page)
def candidate_rows(scan, settings) -> list:
    rows = []
    min_conf = settings["cleanup.min_confidence"]
    allow_pot = settings["cleanup.allow_potential"]
    for f in Finding.query.filter_by(scan_id=scan.id).order_by(Finding.file, Finding.line).all():
        if f.fix_mode == "manual":
            continue
        ok, reason = eligible(f, settings)
        rows.append({
            "id": f.id, "title": f.title, "file": f.file, "line": f.line, "category": f.category, "item_type": f.item_type,
            "size": f.size_bytes, "confidence": f.confidence, "certainty": f.certainty, "severity": f.severity, "fix_mode": f.fix_mode,
            "eligible": ok, "reason": reason, "review_status": f.review_status,
            "checked": ok and f.fix_mode == "auto" and f.certainty == "confirmed" and f.confidence >= min_conf and f.review_status != "rejected",
            "reasons": (f.details_data().get("evidence") or [])[:1],
        })
    return rows


def eligible(f: Finding, settings) -> tuple:
    if f.review_status == "rejected":
        return False, "You rejected this recommendation"
    if f.fix_mode == "manual":
        return False, "No safe automatic fix exists (manual review required)"
    explicit = f.review_status == "approved"
    if not explicit:
        if f.certainty != "confirmed" and not settings["cleanup.allow_potential"]:
            return False, "Potential (unconfirmed) finding - approve it in the analysis report or enable 'allow potential' in Settings"
        if f.confidence < settings["cleanup.min_confidence"]:
            return False, f"Confidence {f.confidence}% is below your threshold of {settings['cleanup.min_confidence']}%"
    return True, ""


# ------------------------------------------------------------------ planning (shared by preview and execute)
def plan_run(scan, ids, settings) -> dict:
    ws, current, _b, _o = _paths(scan)
    findings = {f.id: f for f in Finding.query.filter(Finding.scan_id == scan.id, Finding.id.in_(list(ids))).all()}
    skipped, code_plans, deletes = [], defaultdict(list), []
    for fid in ids:
        f = findings.get(fid)
        if f is None:
            skipped.append({"id": fid, "title": "(unknown item)", "reason": "Not part of this project"})
            continue
        ok, reason = eligible(f, settings)
        if not ok:
            skipped.append({"id": fid, "title": f.title, "file": f.file, "reason": reason})
            continue
        try:
            target = safe_join(current, f.file)
        except ValueError:
            skipped.append({"id": fid, "title": f.title, "file": f.file, "reason": "Path is outside the project"})
            continue
        plan = f.plan_data()
        if not plan:
            skipped.append({"id": fid, "title": f.title, "file": f.file, "reason": "No fix plan stored"})
            continue
        if not target.exists():
            skipped.append({"id": fid, "title": f.title, "file": f.file, "reason": "File no longer exists (already removed?)"})
            continue
        if f.item_type == "file" and f.file_sha and sha256_file(target) != f.file_sha:
            skipped.append({"id": fid, "title": f.title, "file": f.file, "reason": "File changed since the scan - re-scan first"})
            continue
        if f.item_type == "code":
            if f.file_sha and sha256_file(target) != f.file_sha:
                skipped.append({"id": fid, "title": f.title, "file": f.file, "reason": "File changed since the scan - re-scan first"})
                continue
            code_plans[f.file].append((fid, plan))
        else:
            deletes.append((f, plan, target))
    # file/dir deletions
    del_items, deleted_paths = [], []
    for f, plan, target in deletes:
        size = dir_size(target) if target.is_dir() else target.stat().st_size
        del_items.append({"id": f.id, "path": f.file, "is_dir": target.is_dir(), "size": size, "title": f.title})
        deleted_paths.append(f.file.rstrip("/") + "/" if target.is_dir() else f.file)
    # code edits per file
    edits_out, diffs = {}, []
    for rel, plans in code_plans.items():
        if any(rel == d.rstrip("/") or rel.startswith(d) for d in deleted_paths if d.endswith("/")) or rel in deleted_paths:
            for fid, _ in plans:
                skipped.append({"id": fid, "title": findings[fid].title, "file": rel, "reason": "The file/folder is being removed by another selected item"})
            continue
        edits, overlap = fixes.build_edits(plans)
        for fid, why in overlap:
            skipped.append({"id": fid, "title": findings[fid].title, "file": rel, "reason": why})
        target = safe_join(current, rel)
        old = _read(target)
        lines = split_lines(old)
        new_lines = fixes.apply_edits(lines, edits)
        new = "".join(new_lines)
        lang = fixes.language_of(rel)
        ok, msg = fixes.validate_text(lang, rel, _for_validation(new)) if lang else (True, "no syntax check")
        ids_in = [i for e in edits for i in e[3]]
        if not ok:
            for fid in ids_in:
                skipped.append({"id": fid, "title": findings[fid].title, "file": rel, "reason": f"Fix would break the file ({msg}); not applied"})
            continue
        edits_out[rel] = {"old": old, "new": new, "ids": ids_in, "validation": msg, "lang": lang}
        diffs.append(fixes.unified_diff(rel, old, new))
    est = sum(d["size"] for d in del_items) + sum(len(v["old"].encode("utf-8", "surrogateescape")) - len(v["new"].encode("utf-8", "surrogateescape")) for v in edits_out.values())
    applied_ids = [i for v in edits_out.values() for i in v["ids"]] + [d["id"] for d in del_items]
    return {"edits": edits_out, "deletes": del_items, "skipped": skipped, "estimated_bytes": max(0, est), "diff": "\n".join(diffs),
            "applied_ids": applied_ids, "findings": findings}


def preview(scan, ids, settings) -> dict:
    p = plan_run(scan, ids, settings)
    total = scan.total_bytes or 0
    after = max(0, total - p["estimated_bytes"])
    log = [f"> {len(ids)} item(s) selected", f"> {len(p['applied_ids'])} can be applied, {len(p['skipped'])} will be skipped",
           f"> {len(p['edits'])} file(s) edited, {len(p['deletes'])} file/folder(s) removed",
           f"> Estimated reduction: {p['estimated_bytes']} bytes of {total}"]
    log += [f"> SKIP {s.get('file', '')}: {s['reason']}" for s in p["skipped"][:20]]
    return {"applied": len(p["applied_ids"]), "skipped": p["skipped"], "estimated_bytes": p["estimated_bytes"], "current_size": total,
            "estimated_size": after, "reduction_pct": round(100.0 * p["estimated_bytes"] / total, 1) if total else 0.0,
            "files_edited": list(p["edits"]), "deletes": p["deletes"], "diff": p["diff"][:400000], "log": log,
            "validations": {r: v["validation"] for r, v in p["edits"].items()}}


# ------------------------------------------------------------------ execution
def start_run(scan, user_id, ids, kind="cleanup") -> CleanupRun:
    run = CleanupRun(scan_id=scan.id, user_id=user_id, kind=kind, status="Running", log="> Run created",
                     result=json.dumps({"selected": list(ids)}))
    db.session.add(run)
    db.session.commit()
    return run


def _log(run, line):
    run.log = (run.log or "") + "\n" + line
    db.session.commit()


def execute_run(run_id):
    run = db.session.get(CleanupRun, run_id)
    scan = db.session.get(Scan, run.scan_id)
    with _locks[scan.id]:
        try:
            _execute(run, scan)
        except Exception as exc:  # unexpected: restore everything we touched
            db.session.rollback()
            run = db.session.get(CleanupRun, run_id)
            _log(run, f"> UNEXPECTED ERROR: {type(exc).__name__}: {exc}")
            try:
                if run.backup_path:
                    _restore(run, scan)
                    _log(run, "> Everything was restored from the backup.")
            except Exception as exc2:  # pragma: no cover
                _log(run, f"> Restore also failed: {exc2}. Backup kept at {run.backup_path}.")
            run.status, run.finished_at = "Failed", utcnow()
            db.session.commit()


def _execute(run, scan):
    from .tasks import analyze_scan_inner

    settings = store.get_settings(run.user_id)
    ws, current, backups, outputs = _paths(scan)
    ids = json.loads(run.result)["selected"]
    _log(run, f"> Planning {len(ids)} selected item(s)...")
    plan = plan_run(scan, ids, settings)
    items = []
    for s in plan["skipped"]:
        items.append({"id": s["id"], "title": s.get("title"), "file": s.get("file"), "status": "skipped", "reason": s["reason"]})
        _log(run, f"> SKIPPED {s.get('file', '')}: {s['reason']}")
    if not plan["edits"] and not plan["deletes"]:
        run.status, run.finished_at, run.progress = "Completed with warnings", utcnow(), 100
        run.items_skipped = len(items)
        run.result = json.dumps({"selected": ids, "items": items})
        _log(run, "> Nothing to apply. No files were changed and no backup was needed.")
        return
    # ---- backup
    bdir = backups / f"run_{run.id}"
    (bdir / "files").mkdir(parents=True, exist_ok=True)
    manifest = []
    for rel, e in plan["edits"].items():
        dst = bdir / "files" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(current / rel, dst)
        manifest.append({"path": rel, "type": "file", "action": "modified", "sha_before": sha256_file(current / rel), "sha_after": None})
    for d in plan["deletes"]:
        src, dst = current / d["path"], bdir / "files" / d["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        if d["is_dir"]:
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)
        manifest.append({"path": d["path"], "type": "dir" if d["is_dir"] else "file", "action": "deleted",
                         "sha_before": None if d["is_dir"] else sha256_file(src), "sha_after": None})
    (bdir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    run.backup_path, run.backup_available = str(bdir.relative_to(store.instance_dir())), True
    db.session.commit()
    _log(run, f"> Backup created: {len(manifest)} path(s) copied to backups/run_{run.id}")
    findings = plan["findings"]
    total = len(plan["edits"]) + len(plan["deletes"])
    done = removed_bytes = changed = n_removed = 0
    # ---- edits
    for rel, e in plan["edits"].items():
        target = current / rel
        before_size = target.stat().st_size
        try:
            _write_atomic(target, e["new"])
            ok, msg = fixes.validate_text(e["lang"], rel, _for_validation(_read(target))) if e["lang"] else (True, "no syntax check")
        except Exception as exc:
            ok, msg = False, f"write failed: {exc}"
        if not ok:
            shutil.copy2(bdir / "files" / rel, target)
            _log(run, f"> FAILED {rel}: {msg} - file restored")
            for fid in e["ids"]:
                items.append({"id": fid, "title": findings[fid].title, "file": rel, "status": "failed", "reason": msg})
        else:
            changed += 1
            removed_bytes += before_size - target.stat().st_size
            for m in manifest:
                if m["path"] == rel:
                    m["sha_after"] = sha256_file(target)
            _log(run, f"> OK {rel}: {len(e['ids'])} fix(es) applied - {msg}")
            for fid in e["ids"]:
                d = findings[fid].details_data()
                items.append({"id": fid, "title": findings[fid].title, "file": rel, "line": findings[fid].line, "category": findings[fid].category,
                              "status": "applied", "before": d.get("before"), "after": d.get("after"), "validation": msg,
                              "why": d.get("why"), "confidence": findings[fid].confidence})
        done += 1
        run.progress = int(90 * done / total)
        db.session.commit()
    # ---- deletions
    for d in plan["deletes"]:
        target = current / d["path"]
        try:
            fixes.remove_path(target)
            removed_bytes += d["size"]
            n_removed += 1
            f = findings[d["id"]]
            det = f.details_data()
            items.append({"id": d["id"], "title": f.title, "file": d["path"], "category": f.category, "status": "applied", "before": det.get("before"),
                          "after": det.get("after"), "validation": "Removed from working copy (backup kept)", "why": det.get("why"),
                          "confidence": f.confidence, "size": d["size"]})
            _log(run, f"> REMOVED {d['path']}{'/' if d['is_dir'] else ''} ({d['size']} bytes)")
        except OSError as exc:
            items.append({"id": d["id"], "title": d["title"], "file": d["path"], "status": "failed", "reason": str(exc)})
            _log(run, f"> FAILED to remove {d['path']}: {exc}")
        done += 1
        run.progress = int(90 * done / total)
        db.session.commit()
    (bdir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    # ---- post validation: every edited file must still parse
    bad = []
    for rel, e in plan["edits"].items():
        if (current / rel).exists() and e["lang"]:
            ok, msg = fixes.validate_text(e["lang"], rel, _for_validation(_read(current / rel)))
            if not ok:
                bad.append((rel, msg))
    if bad:
        _log(run, f"> POST-VALIDATION FAILED for {bad}; rolling back the whole run")
        _restore(run, scan)
        run.status, run.finished_at, run.progress = "Failed", utcnow(), 100
        run.items_failed = len(bad)
        run.result = json.dumps({"selected": ids, "items": items, "error": str(bad)})
        db.session.commit()
        return
    # ---- patch + summary
    patch = "\n".join(fixes.unified_diff(rel, e["old"], e["new"]) for rel, e in plan["edits"].items())
    patch += "".join(f"\n# removed {'directory' if d['is_dir'] else 'file'}: {d['path']} ({d['size']} bytes)" for d in plan["deletes"])
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / f"run_{run.id}.patch").write_text(patch, encoding="utf-8", errors="replace")
    run.patch_path = str((outputs / f"run_{run.id}.patch").relative_to(store.instance_dir()))
    applied = [i for i in items if i["status"] == "applied"]
    failed = [i for i in items if i["status"] == "failed"]
    skipped = [i for i in items if i["status"] == "skipped"]
    run.files_changed, run.files_removed, run.bytes_removed = changed, n_removed, max(0, removed_bytes)
    run.items_applied, run.items_failed, run.items_skipped = len(applied), len(failed), len(skipped)
    run.status = "Completed" if not failed and not skipped else "Completed with warnings"
    if not applied:
        run.status = "Failed" if failed else "Completed with warnings"
    run.result = json.dumps({"selected": ids, "items": items})
    run.progress, run.finished_at = 95, utcnow()
    _log(run, f"> Done: {len(applied)} applied, {len(skipped)} skipped, {len(failed)} failed; {changed} file(s) edited, {n_removed} removed, {max(0, removed_bytes)} bytes saved")
    db.session.commit()
    _log(run, "> Re-analyzing the cleaned project...")
    analyze_scan_inner(scan.id, settings)
    prune_backups(scan, settings["backup.keep"])
    run = db.session.get(CleanupRun, run.id)
    run.progress = 100
    _log(run, "> Finished")


def _restore(run, scan):
    ws, current, _b, _o = _paths(scan)
    bdir = store.instance_dir() / run.backup_path
    manifest = json.loads((bdir / "manifest.json").read_text())
    for m in manifest:
        src, dst = bdir / "files" / m["path"], current / m["path"]
        if m["action"] == "deleted" and dst.exists():
            fixes.remove_path(dst)
        if m["type"] == "dir":
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, symlinks=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        if m["type"] == "file" and m.get("sha_before") and sha256_file(dst) != m["sha_before"]:
            raise RuntimeError(f"restore verification failed for {m['path']}")


def prune_backups(scan, keep):
    runs = (CleanupRun.query.filter_by(scan_id=scan.id, backup_available=True).order_by(CleanupRun.id.desc()).all())
    for r in runs[keep:]:
        try:
            shutil.rmtree(store.instance_dir() / r.backup_path, ignore_errors=True)
        except Exception:  # pragma: no cover
            pass
        r.backup_available = False
    db.session.commit()


def can_rollback(run) -> tuple:
    if run.status == "Rolled back":
        return False, "Already rolled back"
    if run.status == "Failed":
        return False, "Nothing to undo: this run failed and left the project unchanged"
    if not run.backup_available:
        return False, "Backup no longer available (pruned or never created)"
    newer = CleanupRun.query.filter(CleanupRun.scan_id == run.scan_id, CleanupRun.id > run.id, CleanupRun.status != "Rolled back",
                                    CleanupRun.backup_available.is_(True)).count()
    if newer:
        return False, "Roll back the newer run(s) first (runs are undone newest-first)"
    changed = _changed_since(run)
    if changed:
        return False, f"{changed} was changed after this run, so restoring it would overwrite newer work. Review it manually or use the patch file."
    return True, ""


def _changed_since(run):
    """First path whose current state no longer matches what this run left behind (or None)."""
    scan = db.session.get(Scan, run.scan_id)
    try:
        _ws, current, _b, _o = _paths(scan)
        manifest = json.loads((store.instance_dir() / run.backup_path / "manifest.json").read_text())
    except (OSError, ValueError, TypeError, FileNotFoundError):
        return None
    for m in manifest:
        target = current / m["path"]
        if m["action"] == "deleted":
            if target.exists():
                return m["path"]
        elif m.get("sha_after"):
            if not target.is_file() or sha256_file(target) != m["sha_after"]:
                return m["path"]
    return None


def rollback_run(run_id) -> tuple:
    from .tasks import analyze_scan_inner

    run = db.session.get(CleanupRun, run_id)
    scan = db.session.get(Scan, run.scan_id)
    ok, why = can_rollback(run)
    if not ok:
        return False, why
    with _locks[scan.id]:
        try:
            _restore(run, scan)
        except Exception as exc:
            _log(run, f"> ROLLBACK FAILED: {exc}")
            return False, f"Rollback failed: {exc}"
        run.status, run.rolled_back_at = "Rolled back", utcnow()
        _log(run, "> Rolled back: all files restored from the backup and verified by checksum")
        db.session.commit()
        analyze_scan_inner(scan.id, store.get_settings(run.user_id))
    return True, "Rolled back"


# ------------------------------------------------------------------ cleaned ZIP
def make_zip(scan) -> Path:
    ws, current, _b, outputs = _paths(scan)
    outputs.mkdir(parents=True, exist_ok=True)
    for old in outputs.glob("cleaned_*.zip"):
        old.unlink()
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in scan.project_name)[:60] or "project"
    out = outputs / f"cleaned_{safe}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for r, dirs, files in os.walk(current, followlinks=False):
            dirs.sort()
            for f in sorted(files):
                fp = Path(r) / f
                if fp.is_symlink():
                    continue
                zf.write(fp, (Path(safe) / fp.relative_to(current)).as_posix())
    last = CleanupRun.query.filter_by(scan_id=scan.id).order_by(CleanupRun.id.desc()).first()
    if last:
        last.zip_path = str(out.relative_to(store.instance_dir()))
        db.session.commit()
    return out
