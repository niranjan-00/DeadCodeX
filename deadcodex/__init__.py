"""DeadCodeX application package."""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from flask import Flask

from .extensions import db, login_manager

BASE_DIR = Path(__file__).resolve().parent.parent
HARD_MAX_UPLOAD_MB = 200


def _load_secret_key(instance_path: Path) -> str:
    env = os.environ.get("DEADCODEX_SECRET_KEY")
    if env:
        return env
    instance_path.mkdir(parents=True, exist_ok=True)
    key_file = instance_path / "secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_hex(32)
    key_file.write_text(key)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return key


def create_app(config: dict | None = None) -> Flask:
    config = dict(config or {})
    instance_path = Path(config.pop("INSTANCE_PATH", BASE_DIR / "instance"))
    app = Flask(
        "deadcodex",
        root_path=str(BASE_DIR),
        instance_path=str(instance_path),
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    instance_path.mkdir(parents=True, exist_ok=True)
    app.config.update(
        SECRET_KEY=_load_secret_key(instance_path),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///database.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=(HARD_MAX_UPLOAD_MB + 5) * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        CSRF_ENABLED=True,
        TASKS_SYNC=False,  # tests run background tasks inline
        WORKSPACE_ROOT=str(instance_path / "workspaces"),
        GITHUB_ENV_TOKEN=os.environ.get("DEADCODEX_GITHUB_TOKEN"),
    )
    app.config.update(config)
    Path(app.config["WORKSPACE_ROOT"]).mkdir(parents=True, exist_ok=True)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db.init_app(app)
    login_manager.init_app(app)

    from .security import init_csrf

    init_csrf(app)

    from . import models  # noqa: F401  (register tables)
    from .routes import register_routes

    register_routes(app)

    with app.app_context():
        from .migrations import upgrade
        from .tasks import recover_interrupted

        for action in upgrade():
            app.logger.info("migration: %s", action)
        recover_interrupted()
    return app
