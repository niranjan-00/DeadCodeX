"""DeadCodeX entry point.

    python app.py            -> http://127.0.0.1:5000
    set FLASK_DEBUG=1        -> Flask debug mode (development only!)
"""
import os

from deadcodex import create_app
from deadcodex.extensions import db  # noqa: F401  (re-exported for scripts/tests)
from deadcodex.models import Finding, CleanupRun, Scan, User  # noqa: F401

app = create_app()

if __name__ == "__main__":
    app.run(host=os.environ.get("DEADCODEX_HOST", "127.0.0.1"), port=int(os.environ.get("DEADCODEX_PORT", "5000")),
            debug=os.environ.get("FLASK_DEBUG") == "1")
