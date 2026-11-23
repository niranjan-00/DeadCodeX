"""Per-user settings persistence and workspace path helpers."""
from __future__ import annotations

import json
from pathlib import Path

from flask import current_app

from . import settings_schema as S
from .extensions import db
from .models import UserSetting
from .security import decrypt_secret, encrypt_secret
from .util import utcnow


def _row(user_id, create=False):
    row = UserSetting.query.filter_by(user_id=user_id).first()
    if row is None and create:
        row = UserSetting(user_id=user_id, data=json.dumps(S.defaults()))
        db.session.add(row)
    return row


def get_settings(user_id) -> dict:
    row = _row(user_id)
    return S.load(row.data if row else None)


def save_settings(user_id, values: dict) -> list:
    """Validate + persist. Returns a list of error strings (nothing saved if any)."""
    current = get_settings(user_id)
    clean, errors = S.validate(values, current)
    if errors:
        return errors
    row = _row(user_id, create=True)
    row.data = json.dumps(clean)
    row.updated_at = utcnow()
    db.session.commit()
    return []


def set_github_token(user_id, token: str | None):
    row = _row(user_id, create=True)
    row.github_token_enc = encrypt_secret(token) if token else None
    row.updated_at = utcnow()
    db.session.commit()


def get_github_token(user_id):
    row = _row(user_id)
    tok = decrypt_secret(row.github_token_enc) if row and row.github_token_enc else None
    return tok or current_app.config.get("GITHUB_ENV_TOKEN")


def github_token_status(user_id) -> str:
    row = _row(user_id)
    if row and row.github_token_enc:
        return "saved" if decrypt_secret(row.github_token_enc) else "unreadable"
    return "environment" if current_app.config.get("GITHUB_ENV_TOKEN") else "none"


# ---------------------------------------------------------------- workspace layout
def instance_dir() -> Path:
    return Path(current_app.instance_path)


def workspace(scan) -> Path:
    if not scan.workspace_path:
        raise FileNotFoundError("This project has no stored source (legacy record).")
    return instance_dir() / scan.workspace_path


def new_workspace_rel(user_id, scan_id) -> str:
    return f"workspaces/u{user_id}/s{scan_id}"
