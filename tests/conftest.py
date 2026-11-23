import io
import re
import zipfile

import pytest

from deadcodex import create_app
from deadcodex.extensions import db

SAMPLE = {
    "sample/main.py": (
        "import os\nimport json\nfrom helpers import used_func\n\n\n"
        "def main():\n    unused_local = 5\n    return json.dumps(used_func())\n\n\n"
        "if __name__ == '__main__':\n    main()\n"
    ),
    "sample/helpers.py": (
        "def used_func():\n    return {'a': 1}\n\n\n"
        "def never_called_function():\n    return 42\n"
    ),
    "sample/web/app.js": (
        "import { helper } from './lib.js';\nimport { other } from './lib.js';\n\n"
        "export function run() {\n  return other();\n}\n"
    ),
    "sample/web/lib.js": "export function helper() { return 1; }\nexport function other() { return 2; }\n",
    "sample/__pycache__/main.cpython-311.pyc": "junkbytes" * 200,
    "sample/README.md": "# Sample\n",
}


def make_zip(files: dict, extra=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
        if extra:
            extra(z)
    return buf.getvalue()


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "CSRF_ENABLED": False, "TASKS_SYNC": True, "INSTANCE_PATH": str(tmp_path / "inst"),
                      "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(tmp_path / "t.db")})
    yield app
    with app.app_context():
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, username="alice", email="alice@example.com", password="password123"):
    return client.post("/register", data={"username": username, "email": email, "password": password})


@pytest.fixture
def user(client):
    register(client)
    return client


def upload_zip(client, data: bytes, name="proj.zip", **form):
    return client.post("/upload", data={"file": (io.BytesIO(data), name), **form}, content_type="multipart/form-data")


@pytest.fixture
def scan_id(user):
    r = upload_zip(user, make_zip(SAMPLE), project_name="Sample")
    assert r.status_code == 302, r.data
    return int(re.search(r"/analysis/(\d+)", r.headers["Location"]).group(1))
