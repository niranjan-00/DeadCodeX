# DeadCodeX

Dead-code analysis and safe cleanup for Python, JavaScript and TypeScript projects. Upload a ZIP or import a GitHub repository, review evidence-based findings, approve fixes, clean the project with automatic backups, and download the cleaned ZIP.

## Install and start (Windows)

```bat
py -3 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000, register an account and upload a project.

macOS / Linux: `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt && python app.py`

The database (`instance/database.db`), uploaded workspaces, backups and the generated secret key (`instance/secret_key`) are created automatically. Upgrading an older install is automatic and non-destructive (additive migrations run at startup; `python -m deadcodex.migrations` runs them by hand).

An internet connection is needed in the browser: Tailwind CSS, fonts and icons load from CDNs.

### Optional environment variables
| Variable | Purpose |
|---|---|
| `DEADCODEX_SECRET_KEY` | Session/encryption key (otherwise generated into `instance/secret_key`; keep it - the saved GitHub token is encrypted with a key derived from it) |
| `DEADCODEX_GITHUB_TOKEN` | Server-wide fallback token for private repositories |
| `DATABASE_URL` | Alternative SQLAlchemy database URL |
| `FLASK_DEBUG=1` | Debug mode (never use on a shared machine) |

## Features
- **Upload:** ZIP (type, integrity, size and ratio checks; ZIP-Slip, symlink, encrypted-entry and decompression-bomb protection; automatic project-root detection) and GitHub import (public/private, branch, subfolder; exact commit recorded). Both use the same analysis pipeline. Uploaded code is only read, never executed.
- **Analysis:** unused imports, variables, functions, classes and exports, unreachable code, dead branches, duplicate files and code blocks, unreferenced assets and modules, cache/dependency folders. Each finding is *confirmed* or *potential*, with file, line, snippet, confidence, severity and a plain-language explanation (why, evidence, consequences, recommendation, before/after, auto/manual).
- **Reports:** search, filters, expandable cards, persisted history, JSON export, file inspector (Rectifier).
- **Precision Pruning:** review patterns, approve/reject per item, preview the exact diff, apply with backup, per-file syntax validation and automatic restore.
- **Cleanup:** real candidate list with sizes, preview that matches execution, backups, rollback (blocked if files changed since), patch download, cleaned ZIP download, persistent history.
- **Settings:** profile, password, interface, scan engine, cleanup safety, upload limits, GitHub token (encrypted), retention, idle timeout, purge history, delete account.
- **Documentation:** `/docs`, generated from the running code.

## Tests
```bat
pip install -r requirements-dev.txt
python -m pytest tests -q
```
Optional browser check (drives the real UI in headless Chromium): `playwright install chromium` then `python tests/browser_smoke.py`.

## Known limitations
- Only `.zip` archives are accepted (no TAR/GZ).
- JavaScript/TypeScript analysis is heuristic (lexer + rules, not a full parser). Python uses the real parser. Other languages are counted but not analysed for code.
- Static analysis cannot see dynamic use (reflection, `getattr`, string-built names, framework conventions, public APIs). Such cases are reported as *potential* and are not auto-fixed unless you allow it.
- Validation is syntax-only. Your project's own tests are **never** run (that would execute untrusted code) - run them after downloading the cleaned ZIP.
- Dark theme only. Background tasks run in threads of the single server process (no external queue); a scan interrupted by a restart is marked Failed and can be re-scanned.
- GitHub import was verified with mocked HTTP responses; it was not exercised against live GitHub in the development sandbox.
- Not tested for multi-process / multi-server deployments. Run with `python app.py` (single process) or one worker.

See `CHANGELOG.md` for what changed.
