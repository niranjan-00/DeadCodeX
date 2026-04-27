"""
DeadCodeX Upload Routes
Fixed + Production Ready
"""

import os
import shutil
import zipfile
import tarfile
import subprocess

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_current_user
from werkzeug.utils import secure_filename

from extensions import db
from models import Project, ActivityLog, ScanResult

upload_bp = Blueprint("upload", __name__)


# =====================================================
# Helpers
# =====================================================

def allowed_file(filename):
    if "." not in filename:
        return False

    ext = filename.rsplit(".", 1)[1].lower()
    return ext in current_app.config.get("ALLOWED_EXTENSIONS", set())


def get_extract_dir(project_id):
    return os.path.join(
        current_app.config["UPLOAD_FOLDER"],
        "projects",
        str(project_id)
    )


def safe_remove(path):
    try:
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
    except Exception:
        pass


def count_files_and_lines(directory):
    total_files = 0
    total_lines = 0
    total_size = 0

    skip_dirs = {
        ".git",
        "__pycache__",
        "venv",
        "env",
        "node_modules",
        "dist",
        "build"
    }

    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in skip_dirs]

        for file in files:
            path = os.path.join(root, file)

            try:
                size = os.path.getsize(path)
                total_size += size
                total_files += 1

                if size < 10 * 1024 * 1024:
                    try:
                        with open(path, "r", encoding="utf-8", errors="ignore") as f:
                            total_lines += sum(1 for _ in f)
                    except Exception:
                        pass

            except Exception:
                pass

    return total_files, total_lines, total_size


def detect_language(directory):
    ext_count = {}

    for root, dirs, files in os.walk(directory):
        for file in files:
            if "." in file:
                ext = file.rsplit(".", 1)[1].lower()
                ext_count[ext] = ext_count.get(ext, 0) + 1

    mapping = {
        "py": "python",
        "js": "javascript",
        "ts": "typescript",
        "java": "java",
        "cpp": "cpp",
        "c": "c",
        "php": "php",
        "html": "html",
        "css": "css"
    }

    if not ext_count:
        return "python"

    best = max(ext_count, key=ext_count.get)
    return mapping.get(best, "python")


# =====================================================
# Upload Project
# =====================================================

@upload_bp.route("/upload", methods=["POST"])
@jwt_required()
def upload_project():
    try:
        user = get_current_user()

        source_type = request.form.get("source_type", "upload")
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        language = request.form.get("language", "auto")

        if not name:
            return jsonify({
                "success": False,
                "message": "Project name required"
            }), 400

        project = Project(
            name=name,
            description=description,
            source_type=source_type,
            language="python",
            user_id=user.id
        )

        db.session.add(project)
        db.session.flush()

        extract_dir = get_extract_dir(project.id)
        os.makedirs(extract_dir, exist_ok=True)

        # =========================================
        # Normal File Upload
        # =========================================
        if source_type == "upload":

            if "file" not in request.files:
                return jsonify({
                    "success": False,
                    "message": "No file uploaded"
                }), 400

            file = request.files["file"]

            if file.filename == "":
                return jsonify({
                    "success": False,
                    "message": "Empty filename"
                }), 400

            filename = secure_filename(file.filename)

            if not allowed_file(filename):
                return jsonify({
                    "success": False,
                    "message": "Invalid file type"
                }), 400

            temp_path = os.path.join(
                current_app.config["UPLOAD_FOLDER"],
                filename
            )

            file.save(temp_path)

            # ZIP
            if filename.endswith(".zip"):
                with zipfile.ZipFile(temp_path, "r") as z:
                    z.extractall(extract_dir)

            # TAR / GZ
            elif filename.endswith((".tar", ".gz", ".tgz")):
                with tarfile.open(temp_path, "r:*") as t:
                    t.extractall(extract_dir)

            # Single file
            else:
                shutil.copy(temp_path, os.path.join(extract_dir, filename))

            safe_remove(temp_path)

        # =========================================
        # GitHub Import
        # =========================================
        elif source_type == "github":

            github_url = request.form.get("github_url", "").strip()

            if not github_url:
                return jsonify({
                    "success": False,
                    "message": "GitHub URL required"
                }), 400

            clone_dir = os.path.join(extract_dir, "repo")

            result = subprocess.run(
                ["git", "clone", "--depth", "1", github_url, clone_dir],
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode != 0:
                return jsonify({
                    "success": False,
                    "message": "Git clone failed"
                }), 400

        else:
            return jsonify({
                "success": False,
                "message": "Invalid source type"
            }), 400

        # =========================================
        # Finalize
        # =========================================
        files, lines, size = count_files_and_lines(extract_dir)

        project.file_path = extract_dir
        project.total_files = files
        project.total_lines = lines
        project.size_bytes = size

        if language == "auto":
            project.language = detect_language(extract_dir)
        else:
            project.language = language

        db.session.commit()

        log = ActivityLog(
            user_id=user.id,
            action="project_uploaded",
            entity_type="project",
            entity_id=project.id,
            details=f"{name} uploaded"
        )

        db.session.add(log)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Upload successful",
            "data": {
                "project": project.to_dict()
            }
        }), 201

    except Exception as e:
        db.session.rollback()

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# =====================================================
# List Projects
# =====================================================

@upload_bp.route("/projects", methods=["GET"])
@jwt_required()
def list_projects():
    user = get_current_user()

    projects = Project.query.filter_by(
        user_id=user.id,
        is_active=True
    ).all()

    return jsonify({
        "success": True,
        "data": {
            "projects": [p.to_dict() for p in projects]
        }
    })


# =====================================================
# Single Project
# =====================================================

@upload_bp.route("/projects/<int:project_id>", methods=["GET"])
@jwt_required()
def get_project(project_id):
    user = get_current_user()

    project = Project.query.filter_by(
        id=project_id,
        user_id=user.id
    ).first()

    if not project:
        return jsonify({
            "success": False,
            "message": "Project not found"
        }), 404

    scans = ScanResult.query.filter_by(
        project_id=project.id
    ).all()

    return jsonify({
        "success": True,
        "data": {
            "project": project.to_dict(),
            "scans": [s.to_dict() for s in scans]
        }
    })


# =====================================================
# Delete Project
# =====================================================

@upload_bp.route("/projects/<int:project_id>", methods=["DELETE"])
@jwt_required()
def delete_project(project_id):
    user = get_current_user()

    project = Project.query.filter_by(
        id=project_id,
        user_id=user.id
    ).first()

    if not project:
        return jsonify({
            "success": False,
            "message": "Project not found"
        }), 404

    project.is_active = False
    db.session.commit()

    safe_remove(project.file_path)

    return jsonify({
        "success": True,
        "message": "Deleted"
    })