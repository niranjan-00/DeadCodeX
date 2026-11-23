"""User-configurable settings: one schema drives defaults, validation, the Settings page and docs.

Every key here is *read by real code* (see the `used_by` note). Settings that are not implemented are
deliberately not listed.
"""
from __future__ import annotations

import json
from collections import OrderedDict

DEFAULT_EXCLUDE_DIRS = ["node_modules", ".git", "venv", ".venv", "env", "site-packages", "vendor", "dist", "build", ".tox"]
LANGUAGES = ["python", "javascript", "typescript"]
SENSITIVITY = OrderedDict([
    ("conservative", {"min_confidence": 80, "confirmed_only": True,
                      "label": "Conservative", "help": "Only confirmed findings with confidence >= 80."}),
    ("balanced", {"min_confidence": 50, "confirmed_only": False,
                  "label": "Balanced", "help": "Confirmed and potential findings with confidence >= 50."}),
    ("aggressive", {"min_confidence": 25, "confirmed_only": False,
                    "label": "Aggressive", "help": "Everything, including weak potential findings (confidence >= 25)."}),
])

# key -> (type, default, constraints, label, used_by)
SCHEMA = OrderedDict([
    ("scan.sensitivity", ("choice", "balanced", {"choices": list(SENSITIVITY)}, "Scan sensitivity", "analyzer.engine")),
    ("scan.min_confidence", ("int_or_none", None, {"min": 0, "max": 100}, "Minimum confidence override (blank = use sensitivity)", "analyzer.engine")),
    ("scan.languages", ("multi", list(LANGUAGES), {"choices": LANGUAGES}, "Languages to analyze", "analyzer.engine")),
    ("scan.detect_assets", ("bool", True, {}, "Detect unreferenced assets and modules", "analyzer.engine")),
    ("scan.detect_duplicates", ("bool", True, {}, "Detect duplicate files and duplicated code", "analyzer.engine")),
    ("scan.detect_junk", ("bool", True, {}, "Detect cache/temp files and bundled dependency folders", "analyzer.engine")),
    ("scan.exclude_dirs", ("list", list(DEFAULT_EXCLUDE_DIRS), {"max_items": 50}, "Directories excluded from code analysis", "analyzer.engine")),
    ("cleanup.min_confidence", ("int", 70, {"min": 0, "max": 100}, "Skip cleanup items below this confidence", "cleanup")),
    ("cleanup.allow_potential", ("bool", False, {}, "Allow cleanup of 'potential' (unconfirmed) findings", "cleanup")),
    ("backup.keep", ("int", 10, {"min": 1, "max": 50}, "Backups kept per project", "cleanup")),
    ("upload.max_zip_mb", ("int", 50, {"min": 1, "max": 200}, "Maximum ZIP size (MB)", "routes.upload")),
    ("upload.max_extracted_mb", ("int", 500, {"min": 1, "max": 2000}, "Maximum extracted size (MB)", "archive")),
    ("upload.max_files", ("int", 20000, {"min": 1, "max": 100000}, "Maximum files per project", "archive")),
    ("ui.recent_scans", ("int", 10, {"min": 5, "max": 50}, "Scans shown on the dashboard", "routes.dashboard")),
    ("ui.context_lines", ("int", 3, {"min": 0, "max": 10}, "Context lines around each finding", "analyzer.explain")),
    ("notify.scan_complete", ("bool", True, {}, "Show a notification when a scan finishes", "static/js/app.js")),
    ("notify.cleanup_complete", ("bool", True, {}, "Show a notification when a cleanup finishes", "static/js/app.js")),
    ("retention.days", ("int", 0, {"min": 0, "max": 3650}, "Delete projects older than N days (0 = keep forever)", "tasks.retention")),
    ("auth.idle_timeout_min", ("int", 0, {"min": 0, "max": 1440}, "Sign out after N idle minutes (0 = never)", "app.before_request")),
])


def defaults() -> dict:
    return {k: (list(v[1]) if isinstance(v[1], list) else v[1]) for k, v in SCHEMA.items()}


def _coerce(key, spec, raw):
    typ, default, cons, label, _ = spec
    if typ == "bool":
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("1", "true", "on", "yes")
    if typ == "int":
        try:
            val = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ValueError(f"{label}: must be a whole number")
        if val < cons["min"] or val > cons["max"]:
            raise ValueError(f"{label}: must be between {cons['min']} and {cons['max']}")
        return val
    if typ == "int_or_none":
        if raw is None or str(raw).strip() == "":
            return None
        try:
            val = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ValueError(f"{label}: must be a whole number or blank")
        if val < cons["min"] or val > cons["max"]:
            raise ValueError(f"{label}: must be between {cons['min']} and {cons['max']}")
        return val
    if typ == "choice":
        if raw not in cons["choices"]:
            raise ValueError(f"{label}: must be one of {', '.join(cons['choices'])}")
        return raw
    if typ == "multi":
        vals = raw if isinstance(raw, (list, tuple)) else [raw]
        vals = [v for v in vals if v]
        bad = [v for v in vals if v not in cons["choices"]]
        if bad:
            raise ValueError(f"{label}: unsupported value(s) {', '.join(map(str, bad))}")
        if not vals:
            raise ValueError(f"{label}: select at least one")
        return list(dict.fromkeys(vals))
    if typ == "list":
        if isinstance(raw, str):
            items = [p.strip() for p in raw.replace("\n", ",").split(",")]
        else:
            items = [str(p).strip() for p in raw]
        items = [i for i in items if i]
        if len(items) > cons["max_items"]:
            raise ValueError(f"{label}: at most {cons['max_items']} entries")
        for it in items:
            if "/" in it or "\\" in it or ".." in it or len(it) > 80:
                raise ValueError(f"{label}: '{it}' must be a plain directory name (no slashes or '..')")
        return items
    raise ValueError(f"{key}: unknown type")


def validate(form: dict, current: dict | None = None):
    """Validate submitted values. Returns (clean_settings, errors). Missing keys keep `current`."""
    clean = dict(current or defaults())
    errors = []
    for key, spec in SCHEMA.items():
        if key not in form:
            continue
        try:
            clean[key] = _coerce(key, spec, form[key])
        except ValueError as exc:
            errors.append(str(exc))
    return clean, errors


def load(blob: str | None) -> dict:
    data = defaults()
    if blob:
        try:
            stored = json.loads(blob)
            for k, v in stored.items():
                if k in SCHEMA:
                    try:
                        data[k] = _coerce(k, SCHEMA[k], v)
                    except ValueError:
                        pass
        except (ValueError, TypeError):
            pass
    return data


def effective_thresholds(settings: dict) -> dict:
    preset = SENSITIVITY[settings.get("scan.sensitivity", "balanced")]
    override = settings.get("scan.min_confidence")
    return {
        "min_confidence": override if override is not None else preset["min_confidence"],
        "confirmed_only": preset["confirmed_only"],
    }
