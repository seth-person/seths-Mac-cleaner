"""Self-update from GitHub Releases.

Installed layout (created by install.sh):

  ~/Library/Application Support/Mac Cleaner/
      versions/0.2.0/macclean/...     one folder per installed release
      current -> versions/0.2.0       what the app runs (the launcher puts it on PYTHONPATH)

Updating downloads the release tarball, checks it against the release's
SHA256SUMS, unpacks it into versions/<new>, makes sure it imports, then
repoints `current` in one atomic step and restarts the server. The previous
version is kept so a bad release can be rolled back from the app.

The repository is private, so requests carry a GitHub token (read-only is
enough) stored in the macOS Keychain by install.sh.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__, config

REPO = "seth-person/seths-Mac-cleaner"
API = os.environ.get("MACCLEAN_UPDATE_API") or f"https://api.github.com/repos/{REPO}"
KEYCHAIN_SERVICE = "Mac Cleaner GitHub"
CHECK_EVERY = 6 * 3600
KEEP_VERSIONS = 3


class UpdateError(Exception):
    pass


# -- install location ---------------------------------------------------------
def install_root() -> Path:
    return Path(os.environ.get("MACCLEAN_INSTALL_ROOT")
                or config.home() / "Library" / "Application Support" / "Mac Cleaner")


def running_from_install() -> bool:
    """True when this code was installed by install.sh (not a git checkout)."""
    here = Path(__file__).resolve()
    return str(here).startswith(str((install_root() / "versions").resolve()) + os.sep)


def installed_versions() -> list:
    d = install_root() / "versions"
    if not d.is_dir():
        return []
    return sorted((p.name for p in d.iterdir() if p.is_dir() and not p.name.startswith(".")),
                  key=parse_version)


def current_target() -> str | None:
    cur = install_root() / "current"
    return os.path.basename(os.readlink(cur)) if cur.is_symlink() else None


def parse_version(v: str) -> tuple:
    nums = re.findall(r"\d+", v.lstrip("vV").split("-")[0])
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


# -- GitHub access ------------------------------------------------------------
def get_token() -> str | None:
    tok = os.environ.get("MACCLEAN_GITHUB_TOKEN")
    if tok:
        return tok.strip()
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                                 capture_output=True, text=True, timeout=10)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def save_token(token: str) -> None:
    token = token.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{20,255}", token):
        raise UpdateError("That doesn't look like a GitHub token")
    if sys.platform != "darwin":
        raise UpdateError("Saving the token needs the macOS Keychain")
    user = os.environ.get("USER", "macclean")
    r = subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", user,
                        "-w", token], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise UpdateError("Couldn't save to the Keychain: " + (r.stderr.strip() or "unknown error"))


def _request(url: str, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "mac-cleaner-updater",
                                               "X-GitHub-Api-Version": "2022-11-28"})
    tok = get_token()
    if tok:
        # Unredirected: asset downloads redirect to a pre-signed storage URL
        # that rejects requests carrying a second Authorization header.
        req.add_unredirected_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404) and "api.github.com" in url:
            if not tok:
                msg = "the repository is private and no GitHub token is saved"
            elif e.code == 404:
                msg = "no release was found, or the saved token can't see this repository"
            else:
                msg = "the saved GitHub token was refused (expired?)"
            raise UpdateError(f"GitHub said {e.code}: {msg}.") from e
        raise UpdateError(f"Download failed: HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise UpdateError(f"Couldn't reach GitHub: {e.reason}") from e


def latest_release() -> dict:
    rel = json.loads(_request(f"{API}/releases/latest"))
    assets = {a["name"]: a for a in rel.get("assets", [])}
    version = rel["tag_name"].lstrip("vV")
    tarball = assets.get(f"mac-cleaner-{version}.tar.gz")
    sums = assets.get("SHA256SUMS")
    return {"version": version, "tag": rel["tag_name"], "notes": rel.get("body") or "",
            "url": rel.get("html_url"), "published_at": rel.get("published_at"),
            "tarball": tarball and tarball["url"], "sums": sums and sums["url"],
            "tarball_name": tarball and tarball["name"]}


# -- checking -----------------------------------------------------------------
_cache_lock = threading.Lock()


def check(force: bool = False) -> dict:
    """Is there a newer release? Cached for a few hours unless forced."""
    out = {"current": __version__, "installed": running_from_install(),
           "token": bool(get_token()), "versions": installed_versions(),
           "can_rollback": _previous_version() is not None, "previous": _previous_version()}
    cache = config.app_dir() / "update-check.json"
    with _cache_lock:
        if not force and cache.exists():
            try:
                c = json.loads(cache.read_text())
                if time.time() - c.get("checked", 0) < CHECK_EVERY and c.get("for") == __version__:
                    return {**c["result"], **out}
            except (OSError, ValueError):
                pass
        try:
            rel = latest_release()
            result = {"latest": rel["version"], "notes": rel["notes"], "url": rel["url"],
                      "published_at": rel["published_at"],
                      "available": parse_version(rel["version"]) > parse_version(__version__),
                      "error": None}
        except (UpdateError, KeyError, ValueError) as e:
            result = {"latest": None, "available": False, "error": str(e)}
        result["checked_at"] = time.strftime("%Y-%m-%d %H:%M")
        try:
            cache.write_text(json.dumps({"checked": time.time(), "for": __version__, "result": result}))
        except OSError:
            pass
    return {**result, **out}


# -- installing ---------------------------------------------------------------
def _safe_extract(data: bytes, dest: Path) -> None:
    """Unpack a .tar.gz, refusing links and anything that escapes `dest`."""
    dest = dest.resolve()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        members = tf.getmembers()
        for m in members:
            target = (dest / m.name).resolve()
            if not (str(target) == str(dest) or str(target).startswith(str(dest) + os.sep)):
                raise UpdateError(f"Refusing unsafe path in update: {m.name}")
            if not (m.isfile() or m.isdir()):
                raise UpdateError(f"Refusing link or device in update: {m.name}")
        for m in members:
            m.mode = (m.mode | 0o600) & 0o755
            if hasattr(tarfile, "data_filter"):
                tf.extract(m, dest, filter="data")
            else:
                tf.extract(m, dest)


def _verify(data: bytes, name: str, sums_text: str) -> None:
    want = None
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            want = parts[0].lower()
    if not want:
        raise UpdateError(f"{name} isn't listed in SHA256SUMS")
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise UpdateError("Downloaded update is corrupt (checksum mismatch); nothing was changed")


def _point_current_at(version: str) -> None:
    root = install_root()
    tmp = root / ".current-new"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(os.path.join("versions", version), tmp)
    os.replace(tmp, root / "current")  # atomic: the app is never half-updated


def _previous_version() -> str | None:
    cur = current_target()
    older = [v for v in installed_versions() if cur and parse_version(v) < parse_version(cur)]
    return older[-1] if older else None


def _prune() -> None:
    keep = set(installed_versions()[-KEEP_VERSIONS:]) | {current_target()}
    for v in installed_versions():
        if v not in keep:
            shutil.rmtree(install_root() / "versions" / v, ignore_errors=True)


def install_latest() -> dict:
    if not running_from_install():
        raise UpdateError("This copy runs from source (a git checkout); update it with `git pull`, "
                          "or install the app with install.sh")
    rel = latest_release()
    if parse_version(rel["version"]) <= parse_version(__version__):
        raise UpdateError(f"Already up to date ({__version__})")
    if not rel["tarball"] or not rel["sums"]:
        raise UpdateError(f"Release {rel['tag']} is missing its download files")
    data = _request(rel["tarball"], accept="application/octet-stream")
    sums = _request(rel["sums"], accept="application/octet-stream").decode()
    _verify(data, rel["tarball_name"], sums)

    versions = install_root() / "versions"
    final = versions / rel["version"]
    staging = Path(tempfile.mkdtemp(prefix=".incoming-", dir=versions))
    os.chmod(staging, 0o755)
    try:
        _safe_extract(data, staging)
        if not (staging / "macclean" / "__init__.py").is_file():
            raise UpdateError("The update doesn't contain the app")
        check_import = subprocess.run(
            [sys.executable, "-c", "import macclean.server, macclean; print(macclean.__version__)"],
            cwd=str(staging), capture_output=True, text=True, timeout=60,
            env={**os.environ, "PYTHONPATH": str(staging)})
        if check_import.returncode != 0 or check_import.stdout.strip() != rel["version"]:
            raise UpdateError("The new version failed its start-up check; staying on "
                              f"{__version__}. {check_import.stderr.strip()[-300:]}")
        if final.exists():
            shutil.rmtree(final)
        os.replace(staging, final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    _point_current_at(rel["version"])
    _prune()
    return {"from": __version__, "to": rel["version"]}


def rollback() -> dict:
    prev = _previous_version()
    if not prev:
        raise UpdateError("There's no earlier version to go back to")
    was = current_target()
    _point_current_at(prev)
    return {"from": was, "to": prev}


def restart_later(port: int, delay: float = 0.6) -> None:
    """Re-exec the server (after the HTTP reply has gone out) so new code loads."""
    def go():
        time.sleep(delay)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(install_root() / "current")
        os.execve(sys.executable, [sys.executable, "-m", "macclean", "serve", "--no-browser",
                                   "--port", str(port)], env)
    threading.Thread(target=go, daemon=True).start()
