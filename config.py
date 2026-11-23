import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
UPLOAD_DIR = BASE_DIR / "uploads"

INSTANCE_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)


class Config:
    # App Info
    APP_NAME = "DeadCodeX"
    APP_VERSION = "1.0.0"

    SECRET_KEY = os.getenv("SECRET_KEY", "deadcodex-secret-key")

    DEBUG = False
    TESTING = False

    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///" + str(INSTANCE_DIR / "deadcodex.db")
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # JWT
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "jwt-secret-key")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    JWT_TOKEN_LOCATION = ["headers", "cookies"]
    JWT_COOKIE_SECURE = False
    JWT_COOKIE_CSRF_PROTECT = False

    # Upload
    UPLOAD_FOLDER = str(UPLOAD_DIR)
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024

    # CORS
    CORS_ORIGINS = [
        "http://localhost:3000",
        "http://127.0.0.1:5000",
        "http://localhost:5000"
    ]

    # Admin
    ADMIN_EMAIL = "admin@deadcodex.dev"

    # Limits
    MAX_SCAN_FILES = 10000
    MAX_FILE_SIZE = 10 * 1024 * 1024


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    JWT_COOKIE_SECURE = True


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig
}