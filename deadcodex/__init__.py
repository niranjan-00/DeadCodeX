
"""DeadCodeX application package.

Flask application factory with safe SQLite initialization,
Render persistent-disk support, stable secret-key handling,
and automatic database migrations.
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from flask import Flask
from sqlalchemy.engine import make_url

from .extensions import db, login_manager


BASE_DIR = Path(__file__).resolve().parent.parent
HARD_MAX_UPLOAD_MB = 200

# Render persistent disk mount path.
RENDER_DATA_DIR = Path("/var/data")


def _ensure_directory(path: Path) -> None:
    """Create a directory safely and verify it is writable."""
    path.mkdir(parents=True, exist_ok=True)

    if not path.is_dir():
        raise RuntimeError(f"Required directory does not exist: {path}")

    if not os.access(path, os.W_OK):
        raise RuntimeError(
            f"Directory is not writable: {path}. "
            "Check your Render persistent disk configuration."
        )


def _load_secret_key(instance_path: Path) -> str:
    """Load a stable secret key or generate one on first startup."""

    env_key = os.environ.get("DEADCODEX_SECRET_KEY")

    if env_key:
        if len(env_key) < 32:
            raise RuntimeError(
                "DEADCODEX_SECRET_KEY must contain at least 32 characters."
            )
        return env_key

    _ensure_directory(instance_path)

    key_file = instance_path / "secret_key"

    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()

        if len(key) >= 32:
            return key

        raise RuntimeError(
            "Existing secret_key file is invalid. "
            "Set a permanent DEADCODEX_SECRET_KEY environment variable."
        )

    key = secrets.token_hex(32)

    key_file.write_text(key, encoding="utf-8")

    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass

    return key


def _resolve_database_url(instance_path: Path) -> str:
    """Resolve database URL and prepare SQLite parent directories."""

    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        database_url = f"sqlite:///{instance_path / 'database.db'}"

    # Normalize PostgreSQL URLs supplied by hosting platforms.
    if database_url.startswith("postgres://"):
        database_url = database_url.replace(
            "postgres://",
            "postgresql://",
            1,
        )

    url = make_url(database_url)

    if url.get_backend_name() == "sqlite":

        database = url.database

        # SQLite in-memory database needs no directory.
        if database and database != ":memory:":

            db_path = Path(database)

            if not db_path.is_absolute():
                db_path = instance_path / db_path

            _ensure_directory(db_path.parent)

            # Use an absolute, normalized SQLite path.
            database_url = (
                "sqlite:///"
                + db_path.resolve().as_posix()
            )

    return database_url


def create_app(config: dict | None = None) -> Flask:
    """Create and configure the DeadCodeX Flask application."""

    config = dict(config or {})

    # Select persistent storage when explicitly configured.
    configured_instance = config.pop("INSTANCE_PATH", None)

    if configured_instance:
        instance_path = Path(configured_instance)
    elif os.environ.get("DEADCODEX_DATA_DIR"):
        instance_path = Path(os.environ["DEADCODEX_DATA_DIR"])
    elif os.environ.get("RENDER"):
        # Render deployment: use the persistent disk.
        instance_path = RENDER_DATA_DIR
    else:
        # Local development.
        instance_path = BASE_DIR / "instance"

    instance_path = instance_path.resolve()

    # Create storage directory before accessing SQLite or secret files.
    _ensure_directory(instance_path)

    app = Flask(
        "deadcodex",
        root_path=str(BASE_DIR),
        instance_path=str(instance_path),
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )

    database_url = _resolve_database_url(instance_path)

    app.config.update(
        SECRET_KEY=_load_secret_key(instance_path),

        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,

        MAX_CONTENT_LENGTH=(
            HARD_MAX_UPLOAD_MB + 5
        ) * 1024 * 1024,

        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",

        # Enable secure cookies on HTTPS deployments.
        SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),

        CSRF_ENABLED=True,

        TASKS_SYNC=False,

        # All project workspaces and generated backups
        # remain on the persistent storage directory.
        WORKSPACE_ROOT=str(instance_path / "workspaces"),

        GITHUB_ENV_TOKEN=os.environ.get(
            "DEADCODEX_GITHUB_TOKEN"
        ),
    )

    # Apply testing or deployment-specific overrides.
    app.config.update(config)

    # Ensure configured workspace directory exists.
    workspace_root = Path(app.config["WORKSPACE_ROOT"])
    _ensure_directory(workspace_root)

    # Ensure overridden SQLite URLs are also prepared.
    final_url = make_url(app.config["SQLALCHEMY_DATABASE_URI"])

    if final_url.get_backend_name() == "sqlite":
        database = final_url.database

        if database and database != ":memory:":
            db_path = Path(database)

            if not db_path.is_absolute():
                db_path = instance_path / db_path

            _ensure_directory(db_path.parent)

            app.config["SQLALCHEMY_DATABASE_URI"] = (
                "sqlite:///"
                + db_path.resolve().as_posix()
            )

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s %(levelname)s "
            "%(name)s: %(message)s"
        ),
    )

    app.logger.info("DeadCodeX starting...")
    app.logger.info("Instance directory: %s", instance_path)
    app.logger.info("Workspace directory: %s", workspace_root)

    if final_url.get_backend_name() == "sqlite":
        app.logger.info(
            "Database: SQLite persistent/local storage"
        )
    else:
        app.logger.info(
            "Database backend: %s",
            final_url.get_backend_name(),
        )

    # Initialize extensions.
    db.init_app(app)
    login_manager.init_app(app)

    from .security import init_csrf

    init_csrf(app)

    # Register database models.
    from . import models  # noqa: F401

    # Register application routes.
    from .routes import register_routes

    register_routes(app)

    # Run existing additive migrations.
    with app.app_context():

        from .migrations import upgrade
        from .tasks import recover_interrupted

        app.logger.info("Checking database migrations...")

        migration_actions = upgrade()

        for action in migration_actions:
            app.logger.info(
                "Database migration: %s",
                action,
            )

        if not migration_actions:
            app.logger.info(
                "Database schema is up to date."
            )

        # Recover scans interrupted by previous shutdowns.
        recover_interrupted()

    app.logger.info(
        "DeadCodeX application initialized successfully."
    )

    return app
