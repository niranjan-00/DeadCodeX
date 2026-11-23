"""Import a GitHub repository by downloading GitHub's zipball through the REST API.

* Never runs git and never executes anything from the repository.
* Only talks to api.github.com / codeload.github.com. The access token (if any) is sent only to
  api.github.com and is never logged.
* The downloaded ZIP goes through the same archive validation and analysis pipeline as an upload.
"""
from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

API = "https://api.github.com"
ALLOWED_DOWNLOAD_HOSTS = {"codeload.github.com", "api.github.com"}
USER_AGENT = "DeadCodeX/1.1 (+local analysis tool)"

_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?"
    r"(?:/tree/([^/?#]+)(?:/([^?#]*))?)?/?(?:[?#].*)?$"
)
_REF_RE = re.compile(r"^[A-Za-z0-9._/@+-]{1,200}$")


class GitHubError(Exception):
    """Message is safe to show to the user."""


@dataclass
class RepoRef:
    owner: str
    repo: str
    branch: str | None = None
    subdir: str | None = None

    @property
    def slug(self):
        return f"{self.owner}/{self.repo}"


def parse_github_url(url: str, branch: str | None = None, subdir: str | None = None) -> RepoRef:
    url = (url or "").strip()
    m = _URL_RE.match(url)
    if not m:
        raise GitHubError("That does not look like a GitHub repository URL (expected https://github.com/<owner>/<repo>).")
    owner, repo, tree_branch, tree_sub = m.groups()
    if repo in (".", "..") or owner in (".", ".."):
        raise GitHubError("Invalid repository name.")
    branch = (branch or "").strip() or tree_branch
    subdir = (subdir or "").strip().strip("/") or (tree_sub or "").strip("/") or None
    if branch and (not _REF_RE.match(branch) or ".." in branch or branch.startswith("-")):
        raise GitHubError("Invalid branch name.")
    if subdir and (".." in subdir.split("/") or subdir.startswith(("/", "\\")) or "\\" in subdir):
        raise GitHubError("Invalid subdirectory.")
    return RepoRef(owner, repo, branch or None, subdir)


# ------------------------------------------------------------------ HTTP layer (replaceable in tests)
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _http_open(url: str, token: str | None = None, accept: str = "application/vnd.github+json", timeout: int = 25):
    """Return a response-like object (.status, .headers, .read). Raises urllib errors."""
    host = urllib.parse.urlparse(url).hostname
    if host not in ALLOWED_DOWNLOAD_HOSTS:
        raise GitHubError("Refusing to contact a non-GitHub host.")
    headers = {"User-Agent": USER_AGENT, "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    if token and host == "api.github.com":
        headers["Authorization"] = f"Bearer {token}"
    opener = urllib.request.build_opener(_NoRedirect)
    return opener.open(urllib.request.Request(url, headers=headers), timeout=timeout)


def _reset_text(headers) -> str:
    reset = headers.get("X-RateLimit-Reset") if headers else None
    if reset and str(reset).isdigit():
        when = datetime.fromtimestamp(int(reset), tz=timezone.utc).strftime("%H:%M UTC")
        return f" The limit resets at {when}."
    return ""


def _call(url, token, accept="application/vnd.github+json"):
    try:
        resp = _http_open(url, token, accept)
        return resp
    except urllib.error.HTTPError as e:
        raise _map_http_error(e, token)
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        raise GitHubError(f"Network error while contacting GitHub: {getattr(e, 'reason', e)}. Check your connection and try again.")


def _map_http_error(e: urllib.error.HTTPError, token) -> GitHubError:
    code = e.code
    hdrs = getattr(e, "headers", None) or {}
    remaining = hdrs.get("X-RateLimit-Remaining") if hdrs else None
    if code in (403, 429) and (remaining == "0" or code == 429):
        hint = "" if token else " Adding a GitHub token in Settings raises the limit."
        return GitHubError("GitHub API rate limit reached." + _reset_text(hdrs) + hint)
    if code == 401:
        return GitHubError("GitHub rejected the access token (invalid, expired or revoked). Update it in Settings.")
    if code == 403:
        return GitHubError("GitHub denied access to this repository (the token may lack the 'repo' / contents-read permission).")
    if code == 404:
        if token:
            return GitHubError("Repository, branch or path not found - or your token has no access to it.")
        return GitHubError("Repository or branch not found. If it is private, add a GitHub token in Settings first.")
    if code == 422:
        return GitHubError("GitHub could not resolve that branch or reference.")
    if 500 <= code < 600:
        return GitHubError(f"GitHub is having problems (HTTP {code}). Try again later.")
    return GitHubError(f"GitHub returned an unexpected response (HTTP {code}).")


def _json(url, token):
    resp = _call(url, token)
    try:
        return json.loads(resp.read().decode("utf-8", "replace"))
    except ValueError:
        raise GitHubError("GitHub returned an unreadable response.")


def fetch_repository(ref: RepoRef, token: str | None, dest_zip, max_bytes: int) -> dict:
    """Resolve branch+commit, download the zipball to `dest_zip`. Returns repository metadata."""
    owner, repo = urllib.parse.quote(ref.owner), urllib.parse.quote(ref.repo)
    info = _json(f"{API}/repos/{owner}/{repo}", token)
    default_branch = info.get("default_branch") or "main"
    branch = ref.branch or default_branch
    commit = _json(f"{API}/repos/{owner}/{repo}/commits/{urllib.parse.quote(branch, safe='/')}", token)
    sha = commit.get("sha")
    if not sha or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise GitHubError(f"Branch or reference '{branch}' was not found.")
    # Download by exact commit so the stored sha always matches the analysed content.
    url = f"{API}/repos/{owner}/{repo}/zipball/{sha}"
    resp = None
    for _ in range(4):  # follow a small, host-restricted number of redirects manually
        try:
            resp = _http_open(url, token, accept="application/vnd.github+json")
            break
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                loc = e.headers.get("Location", "")
                if urllib.parse.urlparse(loc).hostname not in ALLOWED_DOWNLOAD_HOSTS:
                    raise GitHubError("GitHub redirected to an unexpected host; download refused.")
                url = loc
                continue
            raise _map_http_error(e, token)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
            raise GitHubError(f"Network error while downloading: {getattr(e, 'reason', e)}.")
    if resp is None:
        raise GitHubError("Too many redirects while downloading the repository.")
    length = resp.headers.get("Content-Length") if resp.headers else None
    if length and length.isdigit() and int(length) > max_bytes:
        raise GitHubError(f"Repository archive is {int(length) / 1048576:.0f} MB; the limit is {max_bytes / 1048576:.0f} MB.")
    written = 0
    try:
        with open(dest_zip, "wb") as out:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise GitHubError(f"Repository archive exceeds the {max_bytes / 1048576:.0f} MB limit.")
                out.write(chunk)
    except (socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        raise GitHubError(f"Network error during download: {e}.")
    return {
        "default_branch": default_branch,
        "branch": branch,
        "commit_sha": sha,
        "private": bool(info.get("private")),
        "html_url": info.get("html_url"),
        "description": info.get("description"),
    }
