"""CSRF protection, login throttling, token encryption and redirect safety (no extra web deps)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from urllib.parse import urlparse

from flask import abort, current_app, request, session


# ---------------------------------------------------------------- CSRF
def csrf_token() -> str:
    tok = session.get("_csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["_csrf"] = tok
    return tok


def init_csrf(app):
    @app.before_request
    def _csrf_protect():
        if not app.config.get("CSRF_ENABLED", True):
            return None
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRFToken") or ""
            expected = session.get("_csrf", "")
            if not expected or not hmac.compare_digest(sent, expected):
                abort(400, description="Missing or invalid CSRF token. Reload the page and try again.")
        return None

    app.jinja_env.globals["csrf_token"] = csrf_token


# ---------------------------------------------------------------- GitHub token encryption
def _fernet():
    from cryptography.fernet import Fernet

    raw = hashlib.sha256(current_app.config["SECRET_KEY"].encode() + b"|deadcodex-github-token").digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(blob: str):
    from cryptography.fernet import InvalidToken

    if not blob:
        return None
    try:
        return _fernet().decrypt(blob.encode()).decode()
    except (InvalidToken, ValueError):
        return None


# ---------------------------------------------------------------- login throttling
class LoginThrottle:
    """Allow `limit` failed attempts per `window` seconds per (username, ip)."""

    def __init__(self, limit=5, window=900):
        self.limit, self.window = limit, window
        self._hits = {}
        self._lock = threading.Lock()

    def _prune(self, key, now):
        self._hits[key] = [t for t in self._hits.get(key, []) if now - t < self.window]

    def blocked(self, key) -> bool:
        with self._lock:
            now = time.time()
            self._prune(key, now)
            return len(self._hits[key]) >= self.limit

    def fail(self, key):
        with self._lock:
            now = time.time()
            self._prune(key, now)
            self._hits[key].append(now)

    def reset(self, key):
        with self._lock:
            self._hits.pop(key, None)


login_throttle = LoginThrottle()


def is_safe_redirect(target: str) -> bool:
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(target)
    if test.scheme or test.netloc:
        return False
    return target.startswith("/") and not target.startswith("//") and not target.startswith("/\\")
