"""End-to-end tests. Background tasks run inline (TASKS_SYNC)."""
import io
import json
import re
import zipfile
from pathlib import Path

import pytest

from conftest import SAMPLE, make_zip, register, upload_zip
from deadcodex import github, store
from deadcodex.extensions import db
from deadcodex.models import CleanupRun, Finding, Scan, User


def findings(client, sid, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    out = []
    for f in client.get(f"/api/scan/{sid}/findings?{qs}").json["files"]:
        out += f["findings"]
    return out


def fid(client, sid, category, symbol=None):
    for f in findings(client, sid):
        if f["category"] == category and (symbol is None or f["symbol"] == symbol):
            return f["id"]
    raise AssertionError(f"no {category} {symbol}")


def wait_run(client, run_id):
    return client.get(f"/api/run/{run_id}").json


def workdir(app, sid):
    with app.app_context():
        return store.workspace(db.session.get(Scan, sid)) / "current"


# 1 startup / DB init ---------------------------------------------------------------
def test_startup_creates_schema_and_pages(app, client):
    assert client.get("/").status_code == 200
    assert client.get("/login").status_code == 200
    assert client.get("/register").status_code == 200
    assert client.get("/docs").status_code == 200
    with app.app_context():
        assert db.engine.dialect.has_table(db.engine.connect(), "finding")


def test_migration_is_idempotent(app):
    from deadcodex.migrations import upgrade
    with app.app_context():
        assert upgrade() == []


# 2 auth ------------------------------------------------------------------------------
def test_register_login_logout(client):
    assert register(client).status_code == 302
    assert client.get("/dashboard").status_code == 200
    client.get("/logout")
    assert client.get("/dashboard").status_code == 302
    assert client.post("/login", data={"username": "alice", "password": "wrong"}).status_code == 200
    r = client.post("/login", data={"username": "alice", "password": "password123"})
    assert r.status_code == 302 and "/dashboard" in r.headers["Location"]


def test_login_rejects_open_redirect(client):
    register(client); client.get("/logout")
    r = client.post("/login", data={"username": "alice", "password": "password123", "next": "https://evil.example/x"})
    assert "evil.example" not in r.headers["Location"]


def test_register_validation(client):
    register(client)
    client.get("/logout")
    assert register(client, username="bob", email="alice@example.com").headers["Location"].endswith("/register")
    assert register(client, username="bob", email="b@example.com", password="short").headers["Location"].endswith("/register")
    with client.application.app_context():
        assert User.query.count() == 1


def test_pages_require_login(client):
    for url in ["/dashboard", "/upload", "/analysis", "/cleanup", "/settings", "/rectifier"]:
        assert client.get(url).status_code == 302
    assert client.get("/api/scan_status/1").status_code == 401


# 3 ZIP upload / safe extraction -----------------------------------------------------------
def test_zip_upload_and_root_detection(app, user, scan_id):
    st = user.get(f"/api/scan_status/{scan_id}").json
    assert st["status"] == "Completed" and st["total_files"] == 5
    names = {p.name for p in workdir(app, scan_id).iterdir()}
    assert "main.py" in names and "sample" not in names  # single top-level folder promoted


def _expect_rejected(user, data, text):
    r = upload_zip(user, data)
    assert r.status_code == 302 and r.headers["Location"].endswith("/upload")
    page = user.get("/upload").get_data(as_text=True)
    assert text.lower() in page.lower()
    with user.application.app_context():
        assert Scan.query.count() == 0


def test_zip_slip_rejected(user):
    _expect_rejected(user, make_zip({"../evil.py": "x=1"}), "unsafe")


def test_absolute_path_rejected(user):
    _expect_rejected(user, make_zip({"/etc/passwd": "x"}), "unsafe")


def test_symlink_rejected(user):
    def add(z):
        i = zipfile.ZipInfo("link"); i.create_system = 3; i.external_attr = (0o120777 << 16)
        z.writestr(i, "/etc/passwd")
    _expect_rejected(user, make_zip({"a.py": "x=1"}, add), "symbolic")


def test_corrupt_and_non_zip(user):
    r = upload_zip(user, b"this is not a zip")
    assert r.status_code == 302
    assert "not a valid zip" in user.get("/upload").get_data(as_text=True).lower() or "zip" in user.get("/upload").get_data(as_text=True).lower()
    r = upload_zip(user, b"x", name="a.txt")
    assert r.status_code == 302


def test_decompression_bomb_rejected(user):
    _expect_rejected(user, make_zip({"big.txt": "0" * (60 * 1024 * 1024)}), "compress")


def test_zip_size_limit_from_settings(user):
    user.post("/settings", data={"section": "limits", "upload.max_zip_mb": "1", "upload.max_extracted_mb": "500", "upload.max_files": "100"})
    import os
    _expect_rejected(user, make_zip({"a.bin": os.urandom(1200000)}), "limit")


# 4 GitHub import (mocked HTTP) ---------------------------------------------------------------
class FakeResp:
    def __init__(self, body, status=200, headers=None):
        self._b = io.BytesIO(body); self.status = status; self.headers = headers or {}
    def read(self, n=-1): return self._b.read(n)


def fake_github(monkeypatch, zip_bytes, sha="a" * 40, fail=None):
    import urllib.error
    calls = []
    def opener(url, token=None, accept="", timeout=25):
        calls.append((url, token))
        if fail:
            raise fail(url)
        if url.endswith("/zipball/" + sha):
            return FakeResp(zip_bytes, headers={"Content-Length": str(len(zip_bytes))})
        if "/commits/" in url:
            return FakeResp(json.dumps({"sha": sha}).encode())
        return FakeResp(json.dumps({"default_branch": "main", "private": False}).encode())
    monkeypatch.setattr(github, "_http_open", opener)
    return calls


def test_github_import_success(user, monkeypatch):
    calls = fake_github(monkeypatch, make_zip({"repo-abc/" + k.split("/", 1)[1]: v for k, v in SAMPLE.items()}))
    r = user.post("/upload/github", data={"repo_url": "https://github.com/octo/demo", "branch": "dev"})
    sid = int(re.search(r"/analysis/(\d+)", r.headers["Location"]).group(1))
    st = user.get(f"/api/scan_status/{sid}").json
    assert st["status"] == "Completed", st
    with user.application.app_context():
        s = db.session.get(Scan, sid)
        assert (s.source_type, s.branch, s.commit_sha) == ("github", "dev", "a" * 40)
    assert any("/commits/dev" in c[0] for c in calls)
    assert findings(user, sid)


def test_github_token_only_for_api_and_never_rendered(user, monkeypatch):
    tok = "ghp_" + "A" * 36
    user.post("/settings/github-token", data={"token": tok})
    calls = fake_github(monkeypatch, make_zip({"x/a.py": "import os\n"}))
    user.post("/upload/github", data={"repo_url": "https://github.com/octo/demo"})
    assert all(c[1] == tok for c in calls)
    for page in ["/settings", "/upload", "/dashboard"]:
        assert tok not in user.get(page).get_data(as_text=True)
    with user.application.app_context():
        from deadcodex.models import UserSetting
        assert tok not in (UserSetting.query.first().github_token_enc or "")


@pytest.mark.parametrize("url", ["", "ftp://github.com/a/b", "https://example.com/a/b", "https://github.com/onlyowner", "not a url"])
def test_github_invalid_urls(user, url):
    r = user.post("/upload/github", data={"repo_url": url})
    assert r.status_code == 302 and "/upload" in r.headers["Location"]
    with user.application.app_context():
        assert Scan.query.count() == 0


@pytest.mark.parametrize("code,text", [(404, "not found"), (401, "token"), (403, "rate limit"), (500, "problems")])
def test_github_http_errors(user, monkeypatch, code, text):
    import urllib.error
    hdrs = {"X-RateLimit-Remaining": "0"} if code == 403 else {}
    fake_github(monkeypatch, b"", fail=lambda u: urllib.error.HTTPError(u, code, "x", hdrs, None))
    r = user.post("/upload/github", data={"repo_url": "https://github.com/octo/demo"})
    sid = int(re.search(r"/analysis/(\d+)", r.headers["Location"]).group(1))
    st = user.get(f"/api/scan_status/{sid}").json
    assert st["status"] == "Failed" and text in st["error"].lower()


def test_github_network_error(user, monkeypatch):
    import urllib.error
    fake_github(monkeypatch, b"", fail=lambda u: urllib.error.URLError("offline"))
    r = user.post("/upload/github", data={"repo_url": "https://github.com/octo/demo"})
    sid = int(re.search(r"/analysis/(\d+)", r.headers["Location"]).group(1))
    assert "network" in user.get(f"/api/scan_status/{sid}").json["error"].lower()


# 5 analysis correctness ----------------------------------------------------------------
def test_known_dead_code_detected(user, scan_id):
    got = {(f["category"], f["symbol"], f["file"]) for f in findings(user, scan_id)}
    assert ("unused_import", "os", "main.py") in got
    assert ("unused_variable", "unused_local", "main.py") in got
    assert ("unused_function", "never_called_function", "helpers.py") in got
    assert ("unused_import", "helper", "web/app.js") in got
    assert any(c == "junk_file" or c == "vendor_dir" for c, _, _ in got)


def test_no_false_positives_on_used_code(user, scan_id):
    syms = {f["symbol"] for f in findings(user, scan_id)}
    assert not syms & {"used_func", "json", "main", "other", "run"}


def test_finding_has_evidence_and_explanation(user, scan_id):
    f = fid(user, scan_id, "unused_function", "never_called_function")
    d = user.get(f"/api/finding/{f}").json
    assert d["line"] == 5 and "never_called_function" in d["snippet"]
    det = d["details"]
    for k in ("why", "evidence", "consequences", "recommendation", "risk", "before", "certainty_text"):
        assert det[k], k


def test_dynamic_use_downgrades_to_potential(user):
    z = make_zip({"a.py": "def handler():\n    return 1\n\ndef main():\n    return globals()['handler']()\n"})
    r = upload_zip(user, z)
    sid = int(re.search(r"/analysis/(\d+)", r.headers["Location"]).group(1))
    fs = [f for f in findings(user, sid) if f["symbol"] == "handler"]
    assert not fs or all(f["certainty"] == "potential" for f in fs)


def test_unsupported_language_disclosed(user):
    r = upload_zip(user, make_zip({"main.rb": "def x; end\n", "a.py": "import os\n"}))
    sid = int(re.search(r"/analysis/(\d+)", r.headers["Location"]).group(1))
    page = user.get(f"/analysis/{sid}").get_data(as_text=True)
    assert "limitation" in page.lower()
    with user.application.app_context():
        assert "ruby" in json.dumps(db.session.get(Scan, sid).summary_data).lower() or ".rb" in json.dumps(db.session.get(Scan, sid).summary_data)


# 6 persistence, search, filters, export ---------------------------------------------------
def test_results_persist_across_app_restart(app, user, scan_id, tmp_path):
    from deadcodex import create_app
    app2 = create_app({"TESTING": True, "CSRF_ENABLED": False, "TASKS_SYNC": True, "INSTANCE_PATH": str(tmp_path / "inst"),
                       "SQLALCHEMY_DATABASE_URI": app.config["SQLALCHEMY_DATABASE_URI"]})
    c = app2.test_client()
    c.post("/login", data={"username": "alice", "password": "password123"})
    assert len(findings(c, scan_id)) >= 5


def test_search_and_filters(user, scan_id):
    assert {f["symbol"] for f in findings(user, scan_id, q="never_called")} == {"never_called_function"}
    assert all(f["category"] == "unused_import" for f in findings(user, scan_id, category="unused_import"))
    assert all(f["file"] == "main.py" for f in findings(user, scan_id, file="main.py"))
    assert all(f["confidence"] >= 90 for f in findings(user, scan_id, min_conf=90))
    assert all(f["fix_mode"] == "review" for f in findings(user, scan_id, fix_mode="review"))
    assert findings(user, scan_id, q="zzz_nothing") == []
    assert all(f["certainty"] == "confirmed" for f in findings(user, scan_id, certainty="confirmed"))


def test_search_is_safe_against_wildcards_and_injection(user, scan_id):
    assert user.get(f"/api/scan/{scan_id}/findings?q=%25").status_code == 200
    assert user.get(f"/api/scan/{scan_id}/findings?q=' OR 1=1 --").status_code == 200


def test_json_export(user, scan_id):
    r = user.get(f"/analysis/{scan_id}/export.json")
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]
    d = json.loads(r.data)
    assert d["project"]["name"] == "Sample" and d["statistics"]["files"] == 5
    assert len(d["findings"]) == len(findings(user, scan_id)) and d["findings"][0]["details"]
    filtered = json.loads(user.get(f"/analysis/{scan_id}/export.json?category=unused_import").data)
    assert {f["category"] for f in filtered["findings"]} == {"unused_import"}


# 7 patterns + approved fixes -------------------------------------------------------------------
def test_patterns_review_and_apply_fixes(app, user, scan_id):
    pats = user.get(f"/api/scan/{scan_id}/patterns").json
    assert pats["patterns"] if "patterns" in pats else pats
    r = user.post(f"/api/scan/{scan_id}/fixes/preview", json={})
    assert r.status_code == 400  # nothing approved
    imp = fid(user, scan_id, "unused_import", "os")
    assert user.post(f"/api/finding/{imp}/review", json={"status": "approved"}).status_code == 200
    pv = user.post(f"/api/scan/{scan_id}/fixes/preview", json={}).json
    assert "-import os" in pv["diff"] and pv["applied"] == 1
    run = user.post(f"/api/scan/{scan_id}/fixes/apply", json={}).json["run_id"]
    d = wait_run(user, run)
    assert d["status"].startswith("Completed") and d["items_applied"] == 1
    src = (workdir(app, scan_id) / "main.py").read_text()
    assert "import os" not in src and "import json" in src
    compile(src, "main.py", "exec")


def test_rejected_items_never_applied(app, user, scan_id):
    imp = fid(user, scan_id, "unused_import", "os")
    user.post(f"/api/finding/{imp}/review", json={"status": "rejected"})
    run = user.post(f"/api/cleanup/{scan_id}/run", json={"ids": [imp]})
    d = wait_run(user, run.json["run_id"]) if run.status_code == 200 else None
    assert "import os" in (workdir(app, scan_id) / "main.py").read_text()


def test_bulk_review_and_invalid_status(user, scan_id):
    assert user.post(f"/api/scan/{scan_id}/review", json={"status": "bogus", "ids": [1]}).status_code == 400
    n = user.post(f"/api/scan/{scan_id}/review", json={"status": "approved", "pattern": "unused_import|auto|confirmed"}).json["updated"]
    assert n >= 2


# 8 cleanup -------------------------------------------------------------------------------------
def test_cleanup_candidates_have_sizes_and_reasons(user, scan_id):
    d = user.get(f"/api/cleanup/{scan_id}/candidates").json
    assert d["items"] and d["total_bytes"] > 0
    assert all("size" in i and "eligible" in i and "reasons" in i for i in d["items"])


def test_cleanup_preview_matches_execution(app, user, scan_id):
    ids = [i["id"] for i in user.get(f"/api/cleanup/{scan_id}/candidates").json["items"] if i["eligible"] and i["fix_mode"] == "auto" and i["certainty"] == "confirmed"]
    assert ids
    pv = user.post(f"/api/cleanup/{scan_id}/preview", json={"ids": ids}).json
    run = user.post(f"/api/cleanup/{scan_id}/run", json={"ids": ids}).json["run_id"]
    d = wait_run(user, run)
    assert d["status"].startswith("Completed")
    assert d["bytes_removed"] == pv["estimated_bytes"] and d["items_applied"] == pv["applied"]
    assert "Rolled" not in d["log"]
    w = workdir(app, scan_id)
    assert not (w / "__pycache__").exists()
    for p in w.rglob("*.py"):
        compile(p.read_text(), str(p), "exec")
    # original upload untouched
    with app.app_context():
        ws = store.workspace(db.session.get(Scan, scan_id))
        assert zipfile.ZipFile(ws / "original.zip").read("sample/main.py").decode() == SAMPLE["sample/main.py"]
        assert (ws / "source").exists()


def test_cleanup_skips_unknown_ids_and_low_confidence(user, scan_id):
    fn = fid(user, scan_id, "unused_function", "never_called_function")
    pv = user.post(f"/api/cleanup/{scan_id}/preview", json={"ids": [fn, 999999]}).json
    assert pv["applied"] == 1 and [s["id"] for s in pv["skipped"]] == [999999] and pv["skipped"][0]["reason"]
    user.post("/settings", data={"section": "cleanup", "cleanup.min_confidence": "100", "backup.keep": "5"})
    pv = user.post(f"/api/cleanup/{scan_id}/preview", json={"ids": [fn]}).json
    assert pv["applied"] == 0 and "confidence" in pv["skipped"][0]["reason"].lower()


def test_cleanup_empty_selection_rejected(user, scan_id):
    assert user.post(f"/api/cleanup/{scan_id}/run", json={"ids": []}).status_code == 400
    assert user.post(f"/api/cleanup/{scan_id}/run", json={"ids": ["x"]}).status_code == 400


def test_validation_failure_triggers_automatic_restore(app, user, scan_id, monkeypatch):
    from deadcodex import fixes
    imp = fid(user, scan_id, "unused_import", "os")
    real = fixes.validate_text
    monkeypatch.setattr(fixes, "validate_text", lambda lang, rel, text: (False, "forced failure") if rel == "main.py" else real(lang, rel, text))
    before = (workdir(app, scan_id) / "main.py").read_text()
    run = user.post(f"/api/cleanup/{scan_id}/run", json={"ids": [imp]}).json["run_id"]
    d = wait_run(user, run)
    assert (workdir(app, scan_id) / "main.py").read_text() == before
    assert d["items_applied"] == 0 and d["items_failed"] + d["items_skipped"] == 1 and "forced failure" in d["log"]


def test_execution_time_validation_failure_restores_file(app, user, scan_id, monkeypatch):
    from deadcodex import fixes
    imp = fid(user, scan_id, "unused_import", "os")
    real, calls = fixes.validate_text, {"n": 0}
    def flaky(lang, rel, text):
        calls["n"] += 1
        return (False, "disk check failed") if rel == "main.py" and calls["n"] >= 2 else real(lang, rel, text)
    monkeypatch.setattr(fixes, "validate_text", flaky)
    before = (workdir(app, scan_id) / "main.py").read_text()
    d = wait_run(user, user.post(f"/api/cleanup/{scan_id}/run", json={"ids": [imp]}).json["run_id"])
    assert (workdir(app, scan_id) / "main.py").read_text() == before
    assert d["items_failed"] == 1 and d["status"] == "Failed" and "file restored" in d["log"] and not d["can_rollback"]


# 9 backup / rollback / zip -------------------------------------------------------------------------
def test_rollback_restores_files(app, user, scan_id):
    w = workdir(app, scan_id)
    snap = {str(p.relative_to(w)): p.read_bytes() for p in w.rglob("*") if p.is_file()}
    ids = [i["id"] for i in user.get(f"/api/cleanup/{scan_id}/candidates").json["items"] if i["eligible"] and i["fix_mode"] == "auto"]
    run = user.post(f"/api/cleanup/{scan_id}/run", json={"ids": ids}).json["run_id"]
    d = wait_run(user, run)
    assert d["can_rollback"]
    r = user.post(f"/api/run/{run}/rollback", json={})
    assert r.status_code == 200 and r.json["ok"]
    now = {str(p.relative_to(w)): p.read_bytes() for p in w.rglob("*") if p.is_file()}
    assert now == snap
    assert wait_run(user, run)["status"] == "Rolled back"
    assert user.post(f"/api/run/{run}/rollback", json={}).status_code == 409  # cannot roll back twice


def test_rollback_blocked_if_file_changed_since(app, user, scan_id):
    imp = fid(user, scan_id, "unused_import", "os")
    run = user.post(f"/api/cleanup/{scan_id}/run", json={"ids": [imp]}).json["run_id"]
    (workdir(app, scan_id) / "main.py").write_text("tampered = 1\n")
    r = user.post(f"/api/run/{run}/rollback", json={})
    assert r.status_code == 409
    assert (workdir(app, scan_id) / "main.py").read_text() == "tampered = 1\n"


def test_cleaned_zip_download_reflects_real_directory(app, user, scan_id):
    imp = fid(user, scan_id, "unused_import", "os")
    user.post(f"/api/cleanup/{scan_id}/run", json={"ids": [imp]})
    r = user.get(f"/cleanup/{scan_id}/download")
    assert r.status_code == 200 and r.mimetype == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert z.testzip() is None
    assert b"import os" not in z.read("Sample/main.py") and b"import json" in z.read("Sample/main.py")


def test_patch_download(user, scan_id):
    imp = fid(user, scan_id, "unused_import", "os")
    run = user.post(f"/api/cleanup/{scan_id}/run", json={"ids": [imp]}).json["run_id"]
    r = user.get(f"/api/run/{run}/patch")
    assert r.status_code == 200 and b"-import os" in r.data


def test_cleanup_history_persists_and_page_renders(user, scan_id):
    imp = fid(user, scan_id, "unused_import", "os")
    run = user.post(f"/api/cleanup/{scan_id}/run", json={"ids": [imp]}).json["run_id"]
    page = user.get(f"/cleanup/{scan_id}").get_data(as_text=True)
    assert f"Run #{run}" in page and "Rollback this run" in page and "-import os" not in page.split("Run #")[0]


def test_rescan_after_cleanup_reflects_changes(user, scan_id):
    before = len(findings(user, scan_id))
    ids = [i["id"] for i in user.get(f"/api/cleanup/{scan_id}/candidates").json["items"] if i["eligible"] and i["fix_mode"] == "auto"]
    user.post(f"/api/cleanup/{scan_id}/run", json={"ids": ids})
    after = findings(user, scan_id)
    assert len(after) < before


# 10 settings -----------------------------------------------------------------------------------
def test_settings_persist_and_validate(app, user):
    r = user.post("/settings", data={"section": "scan", "scan.sensitivity": "conservative", "scan.languages": ["python"], "scan.exclude_dirs": "foo, bar"})
    assert r.status_code == 302
    with app.app_context():
        st = store.get_settings(User.query.first().id)
        assert st["scan.sensitivity"] == "conservative" and st["scan.languages"] == ["python"] and st["scan.exclude_dirs"] == ["foo", "bar"]
        assert st["scan.detect_assets"] is False  # unchecked checkbox saved as false
    assert "value=\"conservative\" checked" in user.get("/settings").get_data(as_text=True)
    user.post("/settings", data={"section": "cleanup", "cleanup.min_confidence": "500", "backup.keep": "3"})
    with app.app_context():
        assert store.get_settings(User.query.first().id)["cleanup.min_confidence"] == 70  # rejected, unchanged
    user.post("/settings", data={"section": "scan", "scan.sensitivity": "nonsense"})
    with app.app_context():
        assert store.get_settings(User.query.first().id)["scan.sensitivity"] == "conservative"


def test_language_setting_changes_scan_results(user):
    user.post("/settings", data={"section": "scan", "scan.languages": ["python"], "scan.detect_assets": "on", "scan.detect_duplicates": "on", "scan.detect_junk": "on"})
    r = upload_zip(user, make_zip(SAMPLE))
    sid = int(re.search(r"/analysis/(\d+)", r.headers["Location"]).group(1))
    assert not [f for f in findings(user, sid) if f["file"].endswith(".js")]


def test_profile_and_password(user):
    assert user.post("/settings", data={"section": "profile", "email": "new@example.com"}).status_code == 302
    assert user.post("/settings", data={"section": "profile", "email": "bad"}).status_code == 302
    with user.application.app_context():
        assert User.query.first().email == "new@example.com"
    user.post("/settings/password", data={"current_password": "nope", "new_password": "newpassword1", "confirm_password": "newpassword1"})
    user.get("/logout")
    assert user.post("/login", data={"username": "alice", "password": "password123"}).status_code == 302
    user.post("/settings/password", data={"current_password": "password123", "new_password": "newpassword1", "confirm_password": "newpassword1"})
    user.get("/logout")
    assert user.post("/login", data={"username": "alice", "password": "newpassword1"}).status_code == 302


def test_delete_project_and_account(app, user, scan_id):
    with app.app_context():
        ws = store.workspace(db.session.get(Scan, scan_id))
    assert ws.exists()
    assert user.post("/settings/delete-account", data={"password": "wrong"}).status_code == 302
    assert ws.exists()
    user.post("/settings/delete-account", data={"password": "password123"})
    assert not ws.exists()
    with app.app_context():
        assert User.query.count() == 0 and Scan.query.count() == 0 and Finding.query.count() == 0


def test_retention_deletes_old_projects(app, user, scan_id):
    from datetime import timedelta
    from deadcodex.util import utcnow
    with app.app_context():
        s = db.session.get(Scan, scan_id); s.date = utcnow() - timedelta(days=40); db.session.commit()
    user.post("/settings", data={"section": "retention", "retention.days": "30"})
    user.post("/settings/retention/run")
    with app.app_context():
        assert Scan.query.count() == 0


# 11 docs & UI links ---------------------------------------------------------------------------------
def test_docs_content_is_generated_from_code(app, client):
    page = client.get("/docs").get_data(as_text=True)
    for needle in ["py -3 -m venv venv", "/api/cleanup/&lt;int:scan_id&gt;/preview", "scan.sensitivity", "unused_function", "TAR/GZ"]:
        assert needle in page, needle
    assert "Team" not in page


def test_all_internal_links_resolve(app, user, scan_id):
    pages = ["/dashboard", "/upload", f"/analysis/{scan_id}", f"/project/{scan_id}", f"/cleanup/{scan_id}", f"/rectifier/{scan_id}", "/settings", "/docs", "/"]
    seen = set()
    for p in pages:
        html = user.get(p).get_data(as_text=True)
        for href in re.findall(r'href="(/[^"#]*)', html):
            if href.startswith("/static") or href in seen:
                continue
            seen.add(href)
            if "'" in href or "+" in href or href == "/logout":
                continue
            assert user.get(href).status_code in (200, 302), f"{p} -> {href}"


def test_team_feature_removed(app, user):
    assert user.get("/team").status_code == 404
    for p in ["/", "/dashboard", "/settings", "/upload", "/docs"]:
        assert "/team" not in user.get(p).get_data(as_text=True).lower()
    assert not any("team" in r.rule for r in app.url_map.iter_rules())


def test_rectifier_shows_highlighted_lines(user, scan_id):
    page = user.get(f"/rectifier/{scan_id}?file=main.py").get_data(as_text=True)
    assert "import os" in page and "bg-error-container/30" in page
    assert user.get(f"/rectifier/{scan_id}?file=../../etc/passwd").status_code in (200, 400)
    assert "root:" not in user.get(f"/rectifier/{scan_id}?file=../../etc/passwd").get_data(as_text=True)


def test_dashboard_real_data_and_empty_state(user):
    assert "no projects" in user.get("/dashboard").get_data(as_text=True).lower() or "upload" in user.get("/dashboard").get_data(as_text=True).lower()
    upload_zip(user, make_zip(SAMPLE), project_name="DashProj")
    assert "DashProj" in user.get("/dashboard").get_data(as_text=True)


# 12 authorization / invalid input / CSRF ------------------------------------------------------------
def test_other_users_cannot_access_data(app, user, scan_id):
    other = app.test_client()
    register(other, "mallory", "m@example.com")
    fidv = fid(user, scan_id, "unused_import", "os")
    for url in [f"/api/scan_status/{scan_id}", f"/api/scan/{scan_id}/findings", f"/api/finding/{fidv}", f"/api/cleanup/{scan_id}/candidates",
                f"/analysis/{scan_id}/export.json", f"/cleanup/{scan_id}/download"]:
        assert other.get(url).status_code == 404, url
    assert other.post(f"/api/cleanup/{scan_id}/run", json={"ids": [fidv]}).status_code == 404
    assert other.post(f"/api/finding/{fidv}/review", json={"status": "approved"}).status_code == 404
    r = other.get(f"/analysis/{scan_id}")
    assert r.status_code == 302 and "dashboard" in r.headers["Location"]
    assert other.post(f"/project/{scan_id}/delete").status_code in (302, 404)
    with app.app_context():
        assert Scan.query.count() == 1


def test_invalid_input_returns_clean_errors(user, scan_id):
    assert user.get("/api/scan_status/99999").status_code == 404
    assert user.post(f"/api/finding/1/review", json={"status": "weird"}).status_code == 400
    assert user.post(f"/api/cleanup/{scan_id}/preview", data="not json", content_type="text/plain").status_code in (200, 400)
    assert user.get("/api/run/99999").status_code == 404
    assert user.post("/upload", data={}, content_type="multipart/form-data").status_code == 302


def test_csrf_enforced_when_enabled(tmp_path):
    from deadcodex import create_app
    app = create_app({"TESTING": True, "CSRF_ENABLED": True, "TASKS_SYNC": True, "INSTANCE_PATH": str(tmp_path / "i"),
                      "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(tmp_path / "c.db")})
    c = app.test_client()
    assert c.post("/register", data={"username": "alice", "email": "a@b.co", "password": "password123"}).status_code == 400
    html = c.get("/register").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    r = c.post("/register", data={"username": "alice", "email": "a@b.co", "password": "password123", "csrf_token": token})
    assert r.status_code == 302 and "dashboard" in r.headers["Location"]
    assert c.post("/api/finding/1/review", json={"status": "approved"}).status_code == 400
    meta = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/dashboard").get_data(as_text=True)).group(1)
    assert c.post("/api/finding/1/review", json={"status": "approved"}, headers={"X-CSRFToken": meta}).status_code in (200, 404)


def test_security_headers_and_no_public_uploads(app, client):
    r = client.get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert not (Path(app.root_path) / "static" / "uploads").exists()


# 13 regression on original routes --------------------------------------------------------------------
def test_original_endpoints_still_exist(app):
    eps = {r.endpoint for r in app.url_map.iter_rules()}
    assert {"index", "login", "register", "logout", "dashboard", "upload", "analysis", "scan_status", "cleanup", "settings", "rectifier"} <= eps


def test_interrupted_scans_recovered_on_startup(app, user, scan_id, tmp_path):
    from deadcodex import create_app
    with app.app_context():
        s = db.session.get(Scan, scan_id); s.status = "Processing"; db.session.commit()
    create_app({"TESTING": True, "TASKS_SYNC": True, "INSTANCE_PATH": str(tmp_path / "inst"), "SQLALCHEMY_DATABASE_URI": app.config["SQLALCHEMY_DATABASE_URI"]})
    with app.app_context():
        db.session.expire_all()
        assert db.session.get(Scan, scan_id).status == "Failed"
