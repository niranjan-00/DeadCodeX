"""Additive, non-destructive schema migrations (no external migration tool needed).

Run automatically at start-up, or manually:  python -m deadcodex.migrations

Rules: only CREATE TABLE (via SQLAlchemy metadata) and ADD COLUMN. Nothing is dropped or rewritten, so
databases created by earlier DeadCodeX versions keep their users and scans.
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from .extensions import db
from .models import SchemaVersion

SCAN_COLUMNS_V1 = {
    "source_type": "VARCHAR(20) DEFAULT 'zip'",
    "source_url": "VARCHAR(500)",
    "branch": "VARCHAR(200)",
    "commit_sha": "VARCHAR(64)",
    "subdir": "VARCHAR(300)",
    "archive_sha256": "VARCHAR(64)",
    "workspace_path": "VARCHAR(500)",
    "progress": "INTEGER DEFAULT 0",
    "progress_message": "VARCHAR(300)",
    "error_message": "TEXT",
    "finished_at": "DATETIME",
    "total_loc": "INTEGER DEFAULT 0",
    "total_bytes": "INTEGER DEFAULT 0",
    "redundant_bytes": "INTEGER DEFAULT 0",
    "confirmed_count": "INTEGER DEFAULT 0",
    "potential_count": "INTEGER DEFAULT 0",
    "zombie_variables": "INTEGER DEFAULT 0",
    "module_count": "INTEGER DEFAULT 0",
    "summary": "TEXT",
}

LATEST = 1


def _add_missing_columns(table: str, columns: dict) -> list:
    insp = inspect(db.engine)
    if table not in insp.get_table_names():
        return []
    existing = {c["name"] for c in insp.get_columns(table)}
    added = []
    for name, ddl in columns.items():
        if name not in existing:
            db.session.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl}'))
            added.append(name)
    return added


def current_version() -> int:
    insp = inspect(db.engine)
    if "schema_version" not in insp.get_table_names():
        return 0
    row = db.session.query(SchemaVersion).order_by(SchemaVersion.version.desc()).first()
    return row.version if row else 0


def upgrade() -> list:
    """Create missing tables, add missing columns, mark legacy rows. Returns a list of actions taken."""
    actions = []
    insp = inspect(db.engine)
    had_scan_table = "scan" in insp.get_table_names()
    db.create_all()  # creates only tables that do not exist yet
    version = current_version()
    if version < 1:
        if had_scan_table:
            added = _add_missing_columns("scan", SCAN_COLUMNS_V1)
            if added:
                actions.append("scan: added columns " + ", ".join(added))
            # Rows from the pre-analysis versions had random fake numbers and no stored source:
            # mark them legacy so the UI never presents them as real analysis results.
            db.session.execute(text(
                "UPDATE scan SET source_type='legacy' WHERE workspace_path IS NULL AND (source_type IS NULL OR source_type='zip')"))
        db.session.add(SchemaVersion(version=1, note="analysis engine columns, findings, cleanup runs, settings"))
        db.session.commit()
        actions.append("schema version 1 recorded")
    else:
        db.session.commit()
    return actions


if __name__ == "__main__":  # pragma: no cover
    from . import create_app

    application = create_app()
    with application.app_context():
        for line in upgrade() or ["database already up to date"]:
            print(line)
