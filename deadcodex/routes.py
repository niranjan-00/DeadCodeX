"""All HTTP routes. Endpoint names of the original app (index, login, register, logout, dashboard, upload,
analysis, scan_status, cleanup, settings, rectifier) are preserved."""
from __future__ import annotations

import json
import re
import shutil
import time
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

from flask import (abort, flash, jsonify, redirect, render_template, request, send_file, session, url_for)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from . import archive, cleanup as cleanup_engine, github, settings_schema as S, store, tasks
from .analyzer.common import CATEGORY_LABELS, split_lines
from .extensions import db, login_manager
from .models import CleanupRun, Finding, Scan, User
from .security import is_safe_redirect, login_throttle
from .util import clean_display_name, human_size, safe_join, sha256_file, timeago, utcnow

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PATTERN_INFO = {
    "unused_import": "Removing an import skips that module's start-up side effects (plugin registration, polyfills, CSS). Standard-library imports are safe; third-party ones need your review.",
    "unused_variable": "Only the assignment is removed; if the value came from a call, the call is kept so behaviour is unchanged.",
    "unreachable_code": "No behavioural change: the code could never run. Only comments between the terminator and the dead code may be lost.",
    "dead_branch": "No behavioural change as long as the condition really is constant.",
    "unused_function": "If the name is used by reflection, plugins, templates or code outside this project, removal would break it.",
    "unused_class": "Frameworks (ORMs, plugin loaders) can discover classes without referencing them by name.",
    "unused_export": "Other repositories or published consumers may import this export.",
    "junk_file": "Generated files are recreated by tools; logs/backups may be the only copy of something you care about.",
    "vendor_dir": "Dependencies are removed from the working copy; reinstall them from the manifest (npm install / pip install -r).",
    "duplicate_file": "A reference to the removed copy would break; DeadCodeX only auto-selects copies whose name is not referenced.",
    "unused_asset": "Assets built from computed names or referenced by external pages look unused to static analysis.",
    "unused_module": "Entry points, plugin systems and build scripts may load it by name.",
    "duplicate_code": "Not auto-fixable: consolidating duplicates needs design decisions.",
}


def register_routes(app):
    # ------------------------------------------------------------------ infrastructure
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith("/api/"):
            return jsonify({"error": "Authentication required"}), 401
        flash("Please sign in to continue.", "error")
        return redirect(url_for("login", next=request.full_path if request.method == "GET" and request.query_string else request.path))

    @app.before_request
    def idle_timeout():
        if not current_user.is_authenticated or request.endpoint in ("static", None):
            return None
        limit = store.get_settings(current_user.id)["auth.idle_timeout_min"]
        now = time.time()
        last = session.get("last_seen")
        if limit and last and now - last > limit * 60:
            logout_user()
            session.pop("last_seen", None)
            flash("You were signed out after being idle.", "error")
            return redirect(url_for("login"))
        session["last_seen"] = now
        return None

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        return resp

    @app.template_filter("size")
    def _size(n):
        return human_size(n)

    @app.template_filter("ago")
    def _ago(dt):
        return timeago(dt)

    @app.template_filter("dt")
    def _dt(d):
        return d.strftime("%b %d, %Y %H:%M UTC") if d else "-"

    @app.context_processor
    def inject():
        ctx = {"cat_labels": CATEGORY_LABELS, "nav_scan": None, "year": utcnow().year}
        if current_user.is_authenticated:
            ctx["nav_scan"] = (Scan.query.filter_by(user_id=current_user.id, status="Completed").order_by(Scan.id.desc()).first())
            ctx["ui_settings"] = {k: v for k, v in store.get_settings(current_user.id).items() if k.startswith("notify.")}
        return ctx

    def wants_json():
        return request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(405)
    @app.errorhandler(500)
    def http_error(e):
        code = getattr(e, "code", 500)
        msg = getattr(e, "description", "Server error") if code != 500 else "Something went wrong on the server."
        if wants_json():
            return jsonify({"error": msg}), code
        return render_template("error.html", code=code, message=msg), code

    @app.errorhandler(413)
    def too_large(e):
        if wants_json():
            return jsonify({"error": "Upload too large"}), 413
        flash("That upload is too large. The absolute maximum is 200 MB.", "error")
        return redirect(url_for("upload"))

    def owned_scan(scan_id, api=False):
        scan = db.session.get(Scan, scan_id)
        if scan is None or scan.user_id != current_user.id:
            abort(404, description="Project not found")
        return scan

    def page_scan(scan_id):
        """Page routes keep the original behaviour: unknown/foreign scans redirect with a flash."""
        scan = db.session.get(Scan, scan_id)
        if scan is None or scan.user_id != current_user.id:
            flash("Access denied", "error")
            return None
        return scan

    # ------------------------------------------------------------------ public + auth
    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        return render_template("index.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            key = (username.lower(), request.remote_addr)
            if login_throttle.blocked(key):
                flash("Too many failed attempts. Try again in a few minutes.", "error")
                return render_template("login.html"), 429
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password, password):
                login_throttle.reset(key)
                session.pop("_csrf", None)
                login_user(user)
                nxt = request.args.get("next") or request.form.get("next")
                return redirect(nxt if nxt and is_safe_redirect(nxt) else url_for("dashboard"))
            login_throttle.fail(key)
            flash("Invalid username or password", "error")
        return render_template("login.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            problems = []
            if not USERNAME_RE.match(username):
                problems.append("Username must be 3-40 characters: letters, digits, '.', '_' or '-'.")
            if not EMAIL_RE.match(email) or len(email) > 150:
                problems.append("Enter a valid email address.")
            if len(password) < 8:
                problems.append("Password must be at least 8 characters.")
            if not problems and User.query.filter_by(username=username).first():
                problems.append("Username already exists")
            if not problems and User.query.filter(func.lower(User.email) == email).first():
                problems.append("Email already registered")
            if problems:
                for p in problems:
                    flash(p, "error")
                return redirect(url_for("register"))
            user = User(username=username, email=email, password=generate_password_hash(password, method="pbkdf2:sha256"))
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Account created successfully!", "success")
            return redirect(url_for("dashboard"))
        return render_template("register.html")

    @app.route("/logout", methods=["GET", "POST"])
    @login_required
    def logout():
        logout_user()
        session.clear()
        return redirect(url_for("index"))

    # ------------------------------------------------------------------ dashboard
    @app.route("/dashboard")
    @login_required
    def dashboard():
        st = store.get_settings(current_user.id)
        q = Scan.query.filter_by(user_id=current_user.id)
        scans = q.order_by(Scan.date.desc()).limit(st["ui.recent_scans"]).all()
        total = q.count()
        completed = q.filter_by(status="Completed").count()
        agg = db.session.query(func.coalesce(func.sum(Scan.confirmed_count), 0), func.coalesce(func.sum(Scan.potential_count), 0),
                               func.coalesce(func.sum(Scan.redundant_bytes), 0), func.coalesce(func.sum(Scan.total_bytes), 0)).filter(
            Scan.user_id == current_user.id, Scan.status == "Completed").one()
        runs = CleanupRun.query.filter_by(user_id=current_user.id)
        stats = {"total_scans": total, "completed": completed, "confirmed": int(agg[0]), "potential": int(agg[1]), "redundant_bytes": int(agg[2]),
                 "pct": round(100.0 * agg[2] / agg[3], 1) if agg[3] else 0.0, "cleanups": runs.filter(CleanupRun.status.like("Completed%")).count(),
                 "bytes_saved": int(db.session.query(func.coalesce(func.sum(CleanupRun.bytes_removed), 0)).filter(
                     CleanupRun.user_id == current_user.id, CleanupRun.status.like("Completed%")).scalar())}
        latest = next((s for s in scans if s.status == "Completed"), None)
        return render_template("dashboard.html", scans=scans, total_scans=total, completed_scans=completed, user=current_user, stats=stats, latest=latest)

    # ------------------------------------------------------------------ upload / import
    def _new_scan(**kw) -> Scan:
        scan = Scan(user_id=current_user.id, status="Importing", progress=0, progress_message="Queued", **kw)
        db.session.add(scan)
        db.session.flush()
        scan.workspace_path = store.new_workspace_rel(current_user.id, scan.id)
        (store.workspace(scan)).mkdir(parents=True, exist_ok=True)
        db.session.commit()
        return scan

    def _discard(scan):
        shutil.rmtree(store.workspace(scan), ignore_errors=True)
        db.session.delete(scan)
        db.session.commit()

    @app.route("/upload", methods=["GET", "POST"])
    @login_required
    def upload():
        st = store.get_settings(current_user.id)
        if request.method == "POST":
            file = request.files.get("file")
            if file is None:
                flash("No file part in the request", "error")
                return redirect(url_for("upload"))
            if not file.filename:
                flash("No file selected", "error")
                return redirect(url_for("upload"))
            if not file.filename.lower().endswith(".zip"):
                flash("Only .zip archives are supported.", "error")
                return redirect(url_for("upload"))
            name = clean_display_name(request.form.get("project_name", "")) or clean_display_name(Path(file.filename).stem) or "Untitled Project"
            subdir = (request.form.get("subdir") or "").strip()
            scan = _new_scan(project_name=name, filename=Path(file.filename).name[:290], source_type="zip", subdir=subdir or None)
            ws = store.workspace(scan)
            try:
                file.save(ws / "original.zip")
                size = (ws / "original.zip").stat().st_size
                if size > st["upload.max_zip_mb"] * 1024 * 1024:
                    raise archive.ArchiveError(f"Archive is {size / 1048576:.1f} MB; your limit is {st['upload.max_zip_mb']} MB (change it in Settings).")
                archive.inspect_zip(ws / "original.zip", tasks._limits(st))  # fail fast with a clear message
                if subdir:
                    archive._check_name(subdir)
                scan.archive_sha256 = sha256_file(ws / "original.zip")
                scan.status = "Processing"
                db.session.commit()
            except archive.ArchiveError as e:
                _discard(scan)
                flash(str(e), "error")
                return redirect(url_for("upload"))
            tasks.submit(app, tasks.zip_import_task, scan.id, st)
            return redirect(url_for("analysis", scan_id=scan.id))
        return render_template("upload.html", st=st, token_status=store.github_token_status(current_user.id))

    @app.route("/upload/github", methods=["POST"])
    @login_required
    def upload_github():
        st = store.get_settings(current_user.id)
        try:
            ref = github.parse_github_url(request.form.get("repo_url"), request.form.get("branch"), request.form.get("subdir"))
        except github.GitHubError as e:
            flash(str(e), "error")
            return redirect(url_for("upload") + "#github")
        name = clean_display_name(request.form.get("project_name", "")) or ref.repo
        scan = _new_scan(project_name=name, filename=ref.slug, source_type="github", source_url=f"https://github.com/{ref.slug}",
                         branch=ref.branch, subdir=ref.subdir)
        tasks.submit(app, tasks.github_import_task, scan.id, st, store.get_github_token(current_user.id))
        return redirect(url_for("analysis", scan_id=scan.id))

    # ------------------------------------------------------------------ analysis
    @app.route("/analysis")
    @login_required
    def analysis_latest():
        s = Scan.query.filter_by(user_id=current_user.id).order_by(Scan.id.desc()).first()
        if not s:
            flash("Upload a project first to see an analysis report.", "error")
            return redirect(url_for("upload"))
        return redirect(url_for("analysis", scan_id=s.id))

    @app.route("/analysis/<int:scan_id>")
    @login_required
    def analysis(scan_id):
        scan = page_scan(scan_id)
        if not scan:
            return redirect(url_for("dashboard"))
        summary = scan.summary_data
        cats = summary.get("categories", {})
        approved = Finding.query.filter_by(scan_id=scan.id, review_status="approved").count()
        return render_template("analysis.html", scan=scan, summary=summary, cats=cats, approved=approved,
                               last_run=CleanupRun.query.filter_by(scan_id=scan.id).order_by(CleanupRun.id.desc()).first())

    @app.route("/project/<int:scan_id>")
    @login_required
    def project(scan_id):
        scan = page_scan(scan_id)
        if not scan:
            return redirect(url_for("dashboard"))
        runs = CleanupRun.query.filter_by(scan_id=scan.id).order_by(CleanupRun.id.desc()).all()
        return render_template("project.html", scan=scan, summary=scan.summary_data, runs=runs)

    @app.route("/project/<int:scan_id>/rescan", methods=["POST"])
    @login_required
    def project_rescan(scan_id):
        scan = owned_scan(scan_id)
        if scan.status in ("Importing", "Processing") or not scan.workspace_path:
            flash("This project cannot be re-scanned right now.", "error")
            return redirect(url_for("project", scan_id=scan.id))
        scan.status, scan.progress = "Processing", 0
        db.session.commit()
        tasks.submit(app, tasks.rescan_task, scan.id, store.get_settings(current_user.id))
        return redirect(url_for("analysis", scan_id=scan.id))

    @app.route("/project/<int:scan_id>/delete", methods=["POST"])
    @login_required
    def project_delete(scan_id):
        scan = owned_scan(scan_id)
        tasks.delete_project(scan)
        flash("Project and its stored files were deleted.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/api/scan_status/<int:scan_id>")
    @login_required
    def scan_status(scan_id):
        scan = db.session.get(Scan, scan_id)
        if not scan or scan.user_id != current_user.id:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"status": scan.status, "progress": scan.progress, "message": scan.progress_message, "error": scan.error_message,
                        "total_files": scan.total_files, "unused_functions": scan.unused_functions, "cleanup_percentage": scan.cleanup_percentage})

    def f_dict(f, detail=False):
        tier = "high" if (f.certainty == "confirmed" and f.confidence >= 80) else "medium" if f.confidence >= 50 else "low"
        d = {"id": f.id, "category": f.category, "label": CATEGORY_LABELS.get(f.category, f.category), "file": f.file, "line": f.line, "end_line": f.end_line,
             "symbol": f.symbol, "title": f.title, "certainty": f.certainty, "confidence": f.confidence, "severity": f.severity, "fix_mode": f.fix_mode,
             "item_type": f.item_type, "size_bytes": f.size_bytes, "review_status": f.review_status, "tier": tier, "language": f.language}
        if detail:
            d["snippet"] = f.snippet
            d["details"] = f.details_data()
        return d

    def apply_filters(q):
        a = request.args
        if a.get("category"):
            q = q.filter(Finding.category.in_(a.get("category").split(",")))
        if a.get("certainty") in ("confirmed", "potential"):
            q = q.filter(Finding.certainty == a["certainty"])
        if a.get("severity") in ("High", "Medium", "Low"):
            q = q.filter(Finding.severity == a["severity"])
        if a.get("fix_mode") in ("auto", "review", "manual"):
            q = q.filter(Finding.fix_mode == a["fix_mode"])
        if a.get("review") in ("pending", "approved", "rejected"):
            q = q.filter(Finding.review_status == a["review"])
        if a.get("min_conf", "").isdigit():
            q = q.filter(Finding.confidence >= int(a["min_conf"]))
        if a.get("file"):
            q = q.filter(Finding.file == a["file"])
        term = (a.get("q") or "").strip()
        if term:
            like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            labels = [k for k, v in CATEGORY_LABELS.items() if term.lower() in v.lower()]
            cond = Finding.file.ilike(like, escape="\\") | Finding.title.ilike(like, escape="\\") | Finding.symbol.ilike(like, escape="\\")
            if labels:
                cond = cond | Finding.category.in_(labels)
            q = q.filter(cond)
        return q

    @app.route("/api/scan/<int:scan_id>/findings")
    @login_required
    def api_findings(scan_id):
        scan = owned_scan(scan_id)
        q = apply_filters(Finding.query.filter_by(scan_id=scan.id))
        rows = q.order_by(Finding.file, Finding.line).all()
        groups = OrderedDict()
        for f in rows:
            groups.setdefault(f.file, []).append(f)
        order = {"high": 0, "medium": 1, "low": 2}
        files = []
        for rel, fs in groups.items():
            ds = [f_dict(f) for f in fs]
            worst = max(ds, key=lambda d: order[d["tier"]])["tier"]
            files.append({"file": rel, "count": len(ds), "tier": worst, "findings": ds, "bytes": sum(d["size_bytes"] for d in ds),
                          "language": next((d["language"] for d in ds if d["language"]), "")})
        sort = request.args.get("sort", "severity")
        if sort == "severity":
            sev = {"High": 0, "Medium": 1, "Low": 2}
            files.sort(key=lambda g: (min(sev[d["severity"]] for d in g["findings"]), -g["count"], g["file"]))
        per = min(100, max(5, int(request.args.get("per_page", 25) or 25)))
        page = max(1, int(request.args.get("page", 1) or 1))
        total_files = len(files)
        return jsonify({"files": files[(page - 1) * per: page * per], "total_findings": len(rows), "total_files": total_files, "page": page,
                        "pages": max(1, -(-total_files // per))})

    @app.route("/api/finding/<int:fid>")
    @login_required
    def api_finding(fid):
        f = db.session.get(Finding, fid)
        if not f or owned_scan_or_none(f.scan_id) is None:
            abort(404, description="Finding not found")
        return jsonify(f_dict(f, detail=True))

    def owned_scan_or_none(scan_id):
        s = db.session.get(Scan, scan_id)
        return s if s and s.user_id == current_user.id else None

    @app.route("/api/finding/<int:fid>/review", methods=["POST"])
    @login_required
    def api_finding_review(fid):
        f = db.session.get(Finding, fid)
        if not f or owned_scan_or_none(f.scan_id) is None:
            abort(404, description="Finding not found")
        status = (request.get_json(silent=True) or {}).get("status")
        if status not in ("approved", "rejected", "pending"):
            abort(400, description="status must be approved, rejected or pending")
        if status == "approved" and f.fix_mode == "manual":
            abort(400, description="This finding has no safe automatic fix, so it cannot be approved for automatic application.")
        f.review_status = status
        db.session.commit()
        return jsonify({"id": f.id, "review_status": f.review_status})

    @app.route("/api/scan/<int:scan_id>/patterns")
    @login_required
    def api_patterns(scan_id):
        scan = owned_scan(scan_id)
        groups = defaultdict(list)
        for f in Finding.query.filter_by(scan_id=scan.id).all():
            groups[(f.category, f.fix_mode, f.certainty)].append(f)
        out = []
        for (cat, mode, cert), fs in groups.items():
            confs = [f.confidence for f in fs]
            out.append({
                "key": f"{cat}|{mode}|{cert}", "category": cat, "label": CATEGORY_LABELS.get(cat, cat), "fix_mode": mode, "certainty": cert,
                "count": len(fs), "files": sorted({f.file for f in fs})[:12], "file_count": len({f.file for f in fs}),
                "confidence_min": min(confs), "confidence_max": max(confs), "bytes": sum(f.size_bytes for f in fs),
                "risk": "Low" if mode == "auto" and cert == "confirmed" and min(confs) >= 85 else "Medium" if min(confs) >= 60 else "High",
                "side_effects": PATTERN_INFO.get(cat, ""), "evidence": (fs[0].details_data().get("evidence") or [])[:2],
                "locations": [{"id": f.id, "file": f.file, "line": f.line, "title": f.title, "confidence": f.confidence, "review": f.review_status} for f in fs[:15]],
                "approved": sum(1 for f in fs if f.review_status == "approved"), "rejected": sum(1 for f in fs if f.review_status == "rejected"),
                "applicable": mode != "manual"})
        out.sort(key=lambda p: (not p["applicable"], p["risk"] != "Low", -p["count"]))
        return jsonify({"patterns": out})

    @app.route("/api/scan/<int:scan_id>/review", methods=["POST"])
    @login_required
    def api_bulk_review(scan_id):
        scan = owned_scan(scan_id)
        body = request.get_json(silent=True) or {}
        status = body.get("status")
        if status not in ("approved", "rejected", "pending"):
            abort(400, description="status must be approved, rejected or pending")
        q = Finding.query.filter_by(scan_id=scan.id)
        if body.get("pattern"):
            try:
                cat, mode, cert = body["pattern"].split("|")
            except ValueError:
                abort(400, description="bad pattern key")
            q = q.filter_by(category=cat, fix_mode=mode, certainty=cert)
        elif body.get("ids"):
            q = q.filter(Finding.id.in_([int(i) for i in body["ids"]]))
        else:
            abort(400, description="pattern or ids required")
        n = 0
        for f in q.all():
            if status == "approved" and f.fix_mode == "manual":
                continue
            f.review_status = status
            n += 1
        db.session.commit()
        return jsonify({"updated": n})

    @app.route("/analysis/<int:scan_id>/export.json")
    @login_required
    def export_json(scan_id):
        scan = owned_scan(scan_id)
        q = apply_filters(Finding.query.filter_by(scan_id=scan.id))
        data = {"generator": "DeadCodeX", "exported_at": utcnow().isoformat() + "Z",
                "project": {"id": scan.id, "name": scan.project_name, "source_type": scan.source_type, "source_url": scan.source_url,
                            "branch": scan.branch, "commit": scan.commit_sha, "subdir": scan.subdir, "status": scan.status,
                            "scanned_at": scan.finished_at.isoformat() + "Z" if scan.finished_at else None},
                "statistics": {"files": scan.total_files, "lines_of_code": scan.total_loc, "total_bytes": scan.total_bytes,
                               "redundant_bytes": scan.redundant_bytes, "redundant_percent": scan.cleanup_percentage,
                               "confirmed": scan.confirmed_count, "potential": scan.potential_count},
                "analysis": scan.summary_data,
                "findings": [f_dict(f, detail=True) for f in q.order_by(Finding.file, Finding.line).all()]}
        resp = app.response_class(json.dumps(data, indent=2), mimetype="application/json")
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", scan.project_name)[:40] or "project"
        resp.headers["Content-Disposition"] = f'attachment; filename="deadcodex_{safe}_{scan.id}.json"'
        return resp

    # ------------------------------------------------------------------ fixes / cleanup
    def parse_ids(body):
        try:
            return [int(i) for i in body.get("ids", [])][:5000]
        except (TypeError, ValueError):
            abort(400, description="ids must be integers")

    @app.route("/api/scan/<int:scan_id>/fixes/preview", methods=["POST"])
    @login_required
    def api_fixes_preview(scan_id):
        scan = owned_scan(scan_id)
        ids = [f.id for f in Finding.query.filter_by(scan_id=scan.id, review_status="approved").all()]
        if not ids:
            return jsonify({"error": "No approved recommendations yet. Open 'Review Patterns' and approve some first."}), 400
        return jsonify(cleanup_engine.preview(scan, ids, store.get_settings(current_user.id)))

    def begin_run(scan, ids, kind):
        if scan.status != "Completed":
            abort(400, description="The project is not ready (analysis still running or failed).")
        if CleanupRun.query.filter_by(scan_id=scan.id, status="Running").count():
            abort(400, description="Another cleanup is already running for this project.")
        if not ids:
            abort(400, description="Nothing selected.")
        run = cleanup_engine.start_run(scan, current_user.id, ids, kind)
        tasks.submit(app, tasks.run_cleanup_task, run.id)
        return jsonify({"run_id": run.id})

    @app.route("/api/scan/<int:scan_id>/fixes/apply", methods=["POST"])
    @login_required
    def api_fixes_apply(scan_id):
        scan = owned_scan(scan_id)
        ids = [f.id for f in Finding.query.filter_by(scan_id=scan.id, review_status="approved").all()]
        return begin_run(scan, ids, "fixes")

    @app.route("/api/cleanup/<int:scan_id>/candidates")
    @login_required
    def api_candidates(scan_id):
        scan = owned_scan(scan_id)
        return jsonify({"items": cleanup_engine.candidate_rows(scan, store.get_settings(current_user.id)), "total_bytes": scan.total_bytes})

    @app.route("/api/cleanup/<int:scan_id>/preview", methods=["POST"])
    @login_required
    def api_cleanup_preview(scan_id):
        scan = owned_scan(scan_id)
        return jsonify(cleanup_engine.preview(scan, parse_ids(request.get_json(silent=True) or {}), store.get_settings(current_user.id)))

    @app.route("/api/cleanup/<int:scan_id>/run", methods=["POST"])
    @login_required
    def api_cleanup_run(scan_id):
        scan = owned_scan(scan_id)
        return begin_run(scan, parse_ids(request.get_json(silent=True) or {}), "cleanup")

    def run_dict(run, full=False):
        d = {"id": run.id, "kind": run.kind, "status": run.status, "progress": run.progress, "log": run.log or "",
             "files_changed": run.files_changed, "files_removed": run.files_removed, "bytes_removed": run.bytes_removed,
             "items_applied": run.items_applied, "items_skipped": run.items_skipped, "items_failed": run.items_failed,
             "started_at": run.started_at.isoformat() if run.started_at else None, "finished_at": run.finished_at.isoformat() if run.finished_at else None,
             "can_rollback": cleanup_engine.can_rollback(run)[0], "rollback_blocked": cleanup_engine.can_rollback(run)[1]}
        if full:
            d["items"] = run.result_data().get("items", [])
        return d

    def owned_run(run_id):
        run = db.session.get(CleanupRun, run_id)
        if not run or run.user_id != current_user.id:
            abort(404, description="Run not found")
        return run

    @app.route("/api/run/<int:run_id>")
    @login_required
    def api_run(run_id):
        return jsonify(run_dict(owned_run(run_id), full=request.args.get("full") == "1"))

    @app.route("/api/run/<int:run_id>/rollback", methods=["POST"])
    @login_required
    def api_rollback(run_id):
        run = owned_run(run_id)
        ok, msg = cleanup_engine.rollback_run(run.id)
        return (jsonify({"ok": True, "message": msg}) if ok else (jsonify({"ok": False, "error": msg}), 409))

    @app.route("/api/run/<int:run_id>/patch")
    @login_required
    def api_run_patch(run_id):
        run = owned_run(run_id)
        if not run.patch_path or not (store.instance_dir() / run.patch_path).exists():
            abort(404, description="No patch for this run")
        return send_file(store.instance_dir() / run.patch_path, as_attachment=True, download_name=f"deadcodex_run_{run.id}.patch", mimetype="text/x-diff")

    @app.route("/cleanup")
    @login_required
    def cleanup_latest():
        s = Scan.query.filter_by(user_id=current_user.id, status="Completed").order_by(Scan.id.desc()).first()
        if not s:
            flash("Run an analysis first - the Cleanup utility works on analysis results.", "error")
            return redirect(url_for("upload"))
        return redirect(url_for("cleanup", scan_id=s.id))

    @app.route("/cleanup/<int:scan_id>", methods=["GET", "POST"])
    @login_required
    def cleanup(scan_id):
        scan = page_scan(scan_id)
        if not scan:
            return redirect(url_for("dashboard"))
        runs = CleanupRun.query.filter_by(scan_id=scan.id).order_by(CleanupRun.id.desc()).all()
        last = runs[0] if runs else None
        return render_template("cleanup.html", scan=scan, runs=runs, last=last, summary=scan.summary_data,
                               rollbackable={r.id: cleanup_engine.can_rollback(r) for r in runs})

    @app.route("/cleanup/<int:scan_id>/download")
    @login_required
    def cleanup_download(scan_id):
        scan = owned_scan(scan_id)
        if scan.status != "Completed":
            abort(400, description="The project is not ready.")
        if CleanupRun.query.filter_by(scan_id=scan.id, status="Running").count():
            abort(400, description="A cleanup is still running; wait for it to finish.")
        out = cleanup_engine.make_zip(scan)
        return send_file(out, as_attachment=True, download_name=out.name, mimetype="application/zip")

    # ------------------------------------------------------------------ rectifier (file-level inspector)
    @app.route("/rectifier")
    @app.route("/rectifier/<int:scan_id>")
    @login_required
    def rectifier(scan_id=None):
        if scan_id is None:
            s = Scan.query.filter_by(user_id=current_user.id, status="Completed").order_by(Scan.id.desc()).first()
            if not s:
                return render_template("rectifier.html", scan=None, files=[], current_file=None, code_lines=[], findings=[])
            return redirect(url_for("rectifier", scan_id=s.id, **request.args))
        scan = page_scan(scan_id)
        if not scan:
            return redirect(url_for("dashboard"))
        files = (db.session.query(Finding.file, func.count(Finding.id)).filter(Finding.scan_id == scan.id, Finding.item_type == "code")
                 .group_by(Finding.file).order_by(func.count(Finding.id).desc(), Finding.file).all())
        current_file = request.args.get("file") or (files[0][0] if files else None)
        code_lines, fl = [], []
        if current_file and scan.workspace_path:
            try:
                p = safe_join(store.workspace(scan) / "current", current_file)
                if p.is_file() and p.stat().st_size < 2 * 1024 * 1024:
                    code_lines = split_lines(p.read_bytes().decode("utf-8", errors="replace"))
                    fl = Finding.query.filter_by(scan_id=scan.id, file=current_file).order_by(Finding.line).all()
            except ValueError:
                abort(400, description="Invalid file path")
        return render_template("rectifier.html", scan=scan, files=files, current_file=current_file, code_lines=code_lines,
                               findings=[f_dict(f, True) for f in fl])

    # ------------------------------------------------------------------ settings
    SECTIONS = {
        "interface": ["ui.recent_scans", "ui.context_lines", "notify.scan_complete", "notify.cleanup_complete"],
        "scan": ["scan.sensitivity", "scan.min_confidence", "scan.languages", "scan.detect_assets", "scan.detect_duplicates", "scan.detect_junk", "scan.exclude_dirs"],
        "cleanup": ["cleanup.min_confidence", "cleanup.allow_potential", "backup.keep"],
        "limits": ["upload.max_zip_mb", "upload.max_extracted_mb", "upload.max_files"],
        "retention": ["retention.days"],
        "auth": ["auth.idle_timeout_min"],
    }

    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def settings():
        if request.method == "POST":
            section = request.form.get("section", "profile")
            if section == "profile":
                new_email = (request.form.get("email") or "").strip().lower()
                if not EMAIL_RE.match(new_email) or len(new_email) > 150:
                    flash("Enter a valid email address.", "error")
                elif new_email != current_user.email.lower() and User.query.filter(func.lower(User.email) == new_email, User.id != current_user.id).first():
                    flash("Email already in use", "error")
                else:
                    current_user.email = new_email
                    db.session.commit()
                    flash("Settings updated successfully", "success")
            elif section in SECTIONS:
                values = {}
                for key in SECTIONS[section]:
                    typ = S.SCHEMA[key][0]
                    if typ == "bool":
                        values[key] = key in request.form
                    elif typ == "multi":
                        values[key] = request.form.getlist(key)
                    elif key in request.form:
                        values[key] = request.form[key]
                errors = store.save_settings(current_user.id, values)
                if errors:
                    for e in errors:
                        flash(e, "error")
                else:
                    flash("Settings updated successfully", "success")
            else:
                flash("Unknown settings section.", "error")
            return redirect(url_for("settings"))
        st = store.get_settings(current_user.id)
        return render_template("settings.html", user=current_user, st=st, schema=S.SCHEMA, sens=S.SENSITIVITY, languages=S.LANGUAGES,
                               token_status=store.github_token_status(current_user.id),
                               counts={"scans": Scan.query.filter_by(user_id=current_user.id).count()})

    @app.route("/settings/password", methods=["POST"])
    @login_required
    def settings_password():
        cur, new, conf = (request.form.get(k) or "" for k in ("current_password", "new_password", "confirm_password"))
        if not check_password_hash(current_user.password, cur):
            flash("Current password is incorrect.", "error")
        elif len(new) < 8:
            flash("New password must be at least 8 characters.", "error")
        elif new != conf:
            flash("New password and confirmation do not match.", "error")
        else:
            current_user.password = generate_password_hash(new, method="pbkdf2:sha256")
            db.session.commit()
            flash("Password changed.", "success")
        return redirect(url_for("settings"))

    @app.route("/settings/github-token", methods=["POST"])
    @login_required
    def settings_github_token():
        if request.form.get("action") == "clear":
            store.set_github_token(current_user.id, None)
            flash("GitHub token removed.", "success")
        else:
            tok = (request.form.get("token") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_\-]{20,255}", tok):
                flash("That does not look like a GitHub token.", "error")
            else:
                store.set_github_token(current_user.id, tok)
                flash("GitHub token saved (encrypted).", "success")
        return redirect(url_for("settings"))

    @app.route("/settings/retention/run", methods=["POST"])
    @login_required
    def settings_retention_run():
        days = store.get_settings(current_user.id)["retention.days"]
        if not days:
            flash("Retention is set to 'keep forever'; nothing to delete.", "error")
        else:
            n = tasks.purge_expired(current_user.id, days)
            flash(f"Deleted {n} project(s) older than {days} days.", "success")
        return redirect(url_for("settings"))

    @app.route("/settings/purge-history", methods=["POST"])
    @login_required
    def settings_purge():
        if not check_password_hash(current_user.password, request.form.get("password") or ""):
            flash("Password incorrect - nothing was deleted.", "error")
            return redirect(url_for("settings"))
        n = 0
        for scan in Scan.query.filter_by(user_id=current_user.id).all():
            tasks.delete_project(scan)
            n += 1
        flash(f"Purged {n} project(s) and all stored files.", "success")
        return redirect(url_for("settings"))

    @app.route("/settings/delete-account", methods=["POST"])
    @login_required
    def settings_delete_account():
        if not check_password_hash(current_user.password, request.form.get("password") or ""):
            flash("Password incorrect - account not deleted.", "error")
            return redirect(url_for("settings"))
        user = db.session.get(User, current_user.id)
        for scan in Scan.query.filter_by(user_id=user.id).all():
            tasks.delete_project(scan)
        from .models import UserSetting

        UserSetting.query.filter_by(user_id=user.id).delete()
        db.session.delete(user)
        db.session.commit()
        logout_user()
        session.clear()
        flash("Your account and all data were deleted.", "success")
        return redirect(url_for("index"))

    # ------------------------------------------------------------------ documentation
    @app.route("/docs")
    @app.route("/documentation")
    def docs():
        from .analyzer.common import ARCHIVE_EXTS, ASSET_EXTS, JS_EXTS, PY_EXTS, TS_EXTS
        from .analyzer.engine import LIMITATIONS

        rules = sorted((r for r in app.url_map.iter_rules() if r.endpoint != "static"), key=lambda r: r.rule)
        api = [{"rule": r.rule, "methods": ",".join(sorted(m for m in r.methods if m not in ("HEAD", "OPTIONS"))), "doc": (app.view_functions[r.endpoint].__doc__ or "").strip()}
               for r in rules]
        return render_template("docs.html", api=api, schema=S.SCHEMA, sens=S.SENSITIVITY, labels=CATEGORY_LABELS, limitations=LIMITATIONS,
                               py=sorted(PY_EXTS), js=sorted(JS_EXTS), ts=sorted(TS_EXTS), assets=sorted(ASSET_EXTS), archives=sorted(ARCHIVE_EXTS),
                               default_excludes=S.DEFAULT_EXCLUDE_DIRS)
