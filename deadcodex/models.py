"""Database models. `User` and `Scan` are the original tables (extended additively);
Finding, CleanupRun, UserSetting and SchemaVersion are new."""
from __future__ import annotations

import json

from flask_login import UserMixin

from .extensions import db
from .util import utcnow


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    scans = db.relationship("Scan", backref="user", lazy=True)


class Scan(db.Model):
    """One uploaded/imported project plus its latest analysis (the project record)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    project_name = db.Column(db.String(150), nullable=False)
    filename = db.Column(db.String(300))
    status = db.Column(db.String(50), default="Pending")  # Pending|Importing|Processing|Completed|Failed
    date = db.Column(db.DateTime, default=utcnow)
    total_files = db.Column(db.Integer, default=0)
    unused_functions = db.Column(db.Integer, default=0)
    cleanup_percentage = db.Column(db.Float, default=0.0)
    # --- added by migration 1 ---
    source_type = db.Column(db.String(20), default="zip")  # zip | github | legacy
    source_url = db.Column(db.String(500))
    branch = db.Column(db.String(200))
    commit_sha = db.Column(db.String(64))
    subdir = db.Column(db.String(300))
    archive_sha256 = db.Column(db.String(64))
    workspace_path = db.Column(db.String(500))  # relative to the instance folder
    progress = db.Column(db.Integer, default=0)
    progress_message = db.Column(db.String(300))
    error_message = db.Column(db.Text)
    finished_at = db.Column(db.DateTime)
    total_loc = db.Column(db.Integer, default=0)
    total_bytes = db.Column(db.Integer, default=0)
    redundant_bytes = db.Column(db.Integer, default=0)
    confirmed_count = db.Column(db.Integer, default=0)
    potential_count = db.Column(db.Integer, default=0)
    zombie_variables = db.Column(db.Integer, default=0)
    module_count = db.Column(db.Integer, default=0)
    summary = db.Column(db.Text)  # JSON: languages, limitations, notes, skipped dirs, settings used

    findings = db.relationship("Finding", backref="scan", lazy=True, cascade="all, delete-orphan")
    runs = db.relationship("CleanupRun", backref="scan", lazy=True, cascade="all, delete-orphan")

    @property
    def summary_data(self) -> dict:
        try:
            return json.loads(self.summary) if self.summary else {}
        except ValueError:
            return {}


class Finding(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(db.Integer, db.ForeignKey("scan.id"), nullable=False, index=True)
    fingerprint = db.Column(db.String(40), index=True)
    category = db.Column(db.String(40), nullable=False, index=True)
    language = db.Column(db.String(20))
    file = db.Column(db.String(600), nullable=False, index=True)  # posix path relative to project root
    line = db.Column(db.Integer, default=0)
    end_line = db.Column(db.Integer, default=0)
    symbol = db.Column(db.String(300))
    title = db.Column(db.String(300))
    certainty = db.Column(db.String(12), default="potential")  # confirmed | potential
    confidence = db.Column(db.Integer, default=0)
    severity = db.Column(db.String(10), default="Low")  # High | Medium | Low
    fix_mode = db.Column(db.String(10), default="manual")  # auto | review | manual
    item_type = db.Column(db.String(8), default="code")  # code | file | dir
    size_bytes = db.Column(db.Integer, default=0)
    file_sha = db.Column(db.String(64))
    snippet = db.Column(db.Text)
    details = db.Column(db.Text)  # JSON explanation
    plan = db.Column(db.Text)  # JSON fix plan
    review_status = db.Column(db.String(10), default="pending")  # pending | approved | rejected

    def details_data(self) -> dict:
        try:
            return json.loads(self.details) if self.details else {}
        except ValueError:
            return {}

    def plan_data(self) -> dict:
        try:
            return json.loads(self.plan) if self.plan else {}
        except ValueError:
            return {}


class CleanupRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(db.Integer, db.ForeignKey("scan.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    kind = db.Column(db.String(12), default="cleanup")  # cleanup | fixes
    status = db.Column(db.String(24), default="Running")  # Running|Completed|Completed with warnings|Failed|Rolled back
    started_at = db.Column(db.DateTime, default=utcnow)
    finished_at = db.Column(db.DateTime)
    progress = db.Column(db.Integer, default=0)
    files_changed = db.Column(db.Integer, default=0)
    files_removed = db.Column(db.Integer, default=0)
    bytes_removed = db.Column(db.Integer, default=0)
    items_applied = db.Column(db.Integer, default=0)
    items_skipped = db.Column(db.Integer, default=0)
    items_failed = db.Column(db.Integer, default=0)
    backup_path = db.Column(db.String(500))
    backup_available = db.Column(db.Boolean, default=False)
    patch_path = db.Column(db.String(500))
    zip_path = db.Column(db.String(500))
    log = db.Column(db.Text, default="")
    result = db.Column(db.Text)  # JSON: per-item outcomes incl. before/after + validation
    rolled_back_at = db.Column(db.DateTime)

    def result_data(self) -> dict:
        try:
            return json.loads(self.result) if self.result else {}
        except ValueError:
            return {}


class UserSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    data = db.Column(db.Text)  # JSON, validated by settings_schema
    github_token_enc = db.Column(db.Text)  # Fernet-encrypted; never rendered or logged
    updated_at = db.Column(db.DateTime, default=utcnow)


class SchemaVersion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.Integer, nullable=False)
    applied_at = db.Column(db.DateTime, default=utcnow)
    note = db.Column(db.String(200))
