# Changelog

## 2.0.0 - upgrade of the original DeadCodeX

### Removed
- **Team feature** (nav entries, landing-page section, links). No team tables or routes existed in the database; nothing needed migrating.
- Fake data: random analysis engine, hard-coded findings, fake stats/"2,000+ teams" claim, fake profile and integrations, fake demo link, public `static/uploads` folder.

### Added
- Application package `deadcodex/` (app factory, models, migrations, routes, tasks); `app.py` remains the entry point and original endpoint names are preserved.
- Safe ZIP extraction and GitHub import; workspaces under `instance/workspaces`.
- Real analyzer (Python AST, JS/TS lexer rules, project-wide reference index, file-level checks), persisted findings, confirmed/potential classification, explanations.
- Search/filter API, JSON export, pattern review with per-item approval, fix preview (diff), apply with backup/validation/rollback.
- Cleanup engine (preview = execution plan), cleaned ZIP, patch files, history, rollback with change detection.
- Settings system driven by one schema; encrypted GitHub token; retention; idle timeout.
- Project detail page, scan history, progress polling, rescan, delete project.
- CSRF protection, login throttling, safe redirects, security headers, per-user authorization on every page and API.
- Documentation page generated from the code; 65 automated tests plus an optional browser smoke test.

### Changed
- Dashboard, Upload, Analysis, Cleanup, Rectifier, Settings pages now use real data; UI theme and layout kept; mobile sidebar toggle added.
- `Scan` table extended with additive columns (legacy rows kept and marked `legacy`).

### Verification (development sandbox)
- `python -m pytest tests -q`: 65 passed.
- Headless-Chromium workflow (register, ZIP upload, findings render, select all, clean, history, rollback) passed with no JavaScript errors.
- Not verified: live GitHub import (mocked only), CDN-styled rendering (no internet in the sandbox), Windows-specific behaviour, running on a multi-process server.
