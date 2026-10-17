"""Self-update from GitHub Releases.

The code runs in one of three ways ("modes"):

  app     Mac Cleaner.app, the standalone app (0.3.0+). The native shell sets
          MACCLEAN_APP_BUNDLE. An update downloads the new app's .zip, checks
          it against SHA256SUMS, unpacks it to a staging folder and checks that
          its engine starts. A small helper script then waits for the app to
          quit, swaps the bundles, keeps the old one for rollback, and reopens
          the app. The engine exits with code 75 to hand over to it.

  legacy  The 0.2.0 browser-based install made by the old install.sh:
            ~/Library/Application Support/Mac Cleaner/versions/<v>/macclean
            ~/Library/Application Support/Mac Cleaner/current -> versions/<v>
          It still updates by code tarball, and offers a one-click switch to
          the standalone app (migrate_to_app).

  source  Run from a git checkout: no self-update, but it can install the app.

The repository is private, so requests carry a GitHub token (read-only is
enough) stored in the macOS Keychain.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from . import __version__, config

REPO = "seth-person/seths-Mac-cleaner"
API = os.environ.get("MACCLEAN_UPDATE_API") or f"https://api.github.com/repos/{REPO}"
KEYCHAIN_SERVICE = "Mac Cleaner GitHub"
CHECK_EVERY = 6 * 3600
KEEP_VERSIONS = 3
APP_NAME = "Mac Cleaner.app"
APP_UPDATE_EXIT = 75  # tells the native shell "the updater is taking over; quit quietly"


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


def mode() -> str:
    if os.environ.get("MACCLEAN_APP_BUNDLE"):
        return "app"
    return "legacy" if running_from_install() else "source"


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
    app_zip = assets.get(f"Mac-Cleaner-{version}.zip")
    dmg = assets.get(f"Mac-Cleaner-{version}.dmg")
    sums = assets.get("SHA256SUMS")
    return {"version": version, "tag": rel["tag_name"], "notes": rel.get("body") or "",
            "url": rel.get("html_url"), "published_at": rel.get("published_at"),
            "tarball": tarball and tarball["url"], "sums": sums and sums["url"],
            "tarball_name": tarball and tarball["name"],
            "app_zip": app_zip and app_zip["url"], "app_zip_name": app_zip and app_zip["name"],
            "dmg_page": rel.get("html_url") if dmg else None}


# -- checking -----------------------------------------------------------------
_cache_lock = threading.Lock()


def check(force: bool = False) -> dict:
    """Is there a newer release? Cached for a few hours unless forced."""
    m = mode()
    if m == "app":
        cleanup_legacy()
        prev = _app_previous_version()
        out = {"versions": [], "can_rollback": prev is not None, "previous": prev,
               "blocked": _app_blocked(app_bundle()), "problem": _last_problem()}
    else:
        out = {"versions": installed_versions(), "blocked": None,
               "can_rollback": m == "legacy" and _previous_version() is not None,
               "previous": _previous_version() if m == "legacy" else None}
    out.update(current=__version__, mode=m, installed=m != "source", token=bool(get_token()))
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
                      "app_available": bool(rel["app_zip"]), "error": None}
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
    m = mode()
    if m == "source":
        raise UpdateError("This copy runs from source (a git checkout), so it can't update itself. "
                          "Use git pull, or install the Mac app.")
    rel = latest_release()
    if parse_version(rel["version"]) <= parse_version(__version__):
        raise UpdateError(f"Already up to date ({__version__})")
    if m == "app":
        return _update_app(rel)
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
    if mode() == "app":
        return _rollback_app()
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


# -- the standalone app -------------------------------------------------------
def app_bundle() -> Path:
    return Path(os.environ.get("MACCLEAN_APP_BUNDLE", ""))


def _previous_app() -> Path:
    return install_root() / "previous" / APP_NAME


def _bundle_version(app: Path) -> str | None:
    try:
        with open(app / "Contents" / "Info.plist", "rb") as f:
            return plistlib.load(f).get("CFBundleShortVersionString")
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None


def _app_previous_version() -> str | None:
    return _bundle_version(_previous_app()) if _previous_app().is_dir() else None


def _app_blocked(bundle: Path) -> str | None:
    """Why the running app can't replace itself, if it can't."""
    s = str(bundle)
    if "/AppTranslocation/" in s or s.startswith("/Volumes/"):
        return ("Mac Cleaner is running straight from the download. Drag it into your Applications "
                "folder, open it from there, then update.")
    if not os.access(bundle.parent, os.W_OK):
        return f"Mac Cleaner can't replace itself in {bundle.parent}. Move it to your Applications folder."
    return None


def _download_verified(url: str, name: str, sums_url: str | None) -> bytes:
    if not url or not sums_url:
        raise UpdateError("This release is missing its download files")
    data = _request(url, accept="application/octet-stream")
    _verify(data, name, _request(sums_url, accept="application/octet-stream").decode())
    return data


def _unzip(data: bytes, dest: Path) -> None:
    """Unpack an app .zip, keeping symlinks and permissions (ditto on macOS)."""
    dest.mkdir(parents=True, exist_ok=True)
    zpath = dest.parent / (dest.name + ".zip")
    zpath.write_bytes(data)
    try:
        if shutil.which("ditto"):
            r = subprocess.run(["ditto", "-x", "-k", str(zpath), str(dest)], capture_output=True, text=True)
            if r.returncode != 0:
                raise UpdateError("Couldn't unpack the update: " + r.stderr.strip())
            return
        root = dest.resolve()
        with zipfile.ZipFile(zpath) as zf:
            for info in zf.infolist():
                target = (dest / info.filename).resolve()
                if not str(target).startswith(str(root) + os.sep):
                    raise UpdateError(f"Refusing unsafe path in update: {info.filename}")
                mode_bits = info.external_attr >> 16
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                elif stat.S_ISLNK(mode_bits):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(zf.read(info).decode(), target)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(info))
                    os.chmod(target, (mode_bits & 0o777) or 0o644)
    finally:
        zpath.unlink()


def _check_staged_engine(app: Path, version: str) -> None:
    res = app / "Contents" / "Resources"
    py = res / "python" / "bin" / "python3"
    r = subprocess.run([str(py), "-c", "import macclean.server, macclean; print(macclean.__version__)"],
                       capture_output=True, text=True, timeout=120,
                       env={**os.environ, "PYTHONPATH": str(res / "app"), "PYTHONHOME": str(res / "python"),
                            "PYTHONDONTWRITEBYTECODE": "1"})
    if r.returncode != 0 or r.stdout.strip() != version:
        raise UpdateError("The new version failed its start-up check, so nothing was changed. "
                          + r.stderr.strip()[-300:])


def _stage_app(rel: dict) -> Path:
    data = _download_verified(rel["app_zip"], rel["app_zip_name"], rel["sums"])
    staging = install_root() / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    _unzip(data, staging / rel["version"])
    app = staging / rel["version"] / APP_NAME
    if _bundle_version(app) != rel["version"]:
        raise UpdateError("The downloaded app isn't the version it claims to be")
    _check_staged_engine(app, rel["version"])
    if shutil.which("xattr"):
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(app)], capture_output=True)
    return app


SWAP_SCRIPT = r"""#!/bin/bash
# Mac Cleaner updater: wait for the app to quit, swap bundles, reopen.
pid="$1"; current="$2"; new="$3"; previous="$4"; result="$5"
for _ in $(seq 1 300); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
mkdir -p "$(dirname "$previous")"
hold="$previous.swap"
rm -rf "$hold"
if ! err="$(mv "$current" "$hold" 2>&1)"; then
  echo "failed: $err" > "$result"
elif ! err="$(mv "$new" "$current" 2>&1)"; then
  mv "$hold" "$current"
  echo "failed: $err" > "$result"
else
  rm -rf "$previous"
  mv "$hold" "$previous"
  echo "ok" > "$result"
fi
open "$current"
"""


def _result_file() -> Path:
    return install_root() / "last-update.txt"


_problem_seen = {}


def _last_problem() -> str | None:
    """last_update_problem(), but remembered for this run so every check shows it."""
    if "msg" not in _problem_seen:
        _problem_seen["msg"] = last_update_problem()
    return _problem_seen["msg"]


def last_update_problem() -> str | None:
    """If the last swap failed (e.g. macOS blocked it), explain once, then forget."""
    f = _result_file()
    try:
        text = f.read_text().strip()
        f.unlink()
    except OSError:
        return None
    if not text.startswith("failed"):
        return None
    return ("The last update couldn't replace the app, so Mac Cleaner kept the version you had. "
            "macOS may have blocked it: open System Settings → Privacy & Security → App Management, "
            "turn on Mac Cleaner, then try the update again. (" + text[len("failed: "):][:200] + ")")


def _swap_to(new_app: Path):
    """Hand over to the swap script; the engine then exits with APP_UPDATE_EXIT."""
    script = install_root() / "swap.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(SWAP_SCRIPT)
    log = open(config.home() / "Library" / "Logs" / "Mac Cleaner.log", "a") \
        if (config.home() / "Library" / "Logs").is_dir() else subprocess.DEVNULL
    return subprocess.Popen(["/bin/bash", str(script), str(_app_pid()), str(app_bundle()), str(new_app),
                             str(_previous_app()), str(_result_file())],
                            stdout=log, stderr=log, start_new_session=True)


def _app_pid() -> int:
    return os.getppid()  # the native shell started the engine


def _update_app(rel: dict) -> dict:
    blocked = _app_blocked(app_bundle())
    if blocked:
        raise UpdateError(blocked)
    if not rel["app_zip"]:
        raise UpdateError(f"Release {rel['tag']} has no app download")
    staged = _stage_app(rel)
    _swap_to(staged)
    return {"from": __version__, "to": rel["version"], "relaunch": True}


def _rollback_app() -> dict:
    prev = _app_previous_version()
    if not prev:
        raise UpdateError("There's no earlier version to go back to")
    blocked = _app_blocked(app_bundle())
    if blocked:
        raise UpdateError(blocked)
    _swap_to(_previous_app())
    return {"from": __version__, "to": prev, "relaunch": True}


def exit_for_relaunch(delay: float = 0.8) -> None:
    """After the HTTP reply has gone out, quit so the swap script can take over."""
    def go():
        time.sleep(delay)
        os._exit(APP_UPDATE_EXIT)
    threading.Thread(target=go, daemon=True).start()


def applications_dir() -> Path:
    override = os.environ.get("MACCLEAN_APPS_DIR")
    if override:
        return Path(override)
    return Path("/Applications") if os.access("/Applications", os.W_OK) else config.home() / "Applications"


def _is_legacy_launcher(app: Path) -> bool:
    exe = app / "Contents" / "MacOS" / "Mac Cleaner"
    try:
        return exe.is_file() and exe.read_bytes()[:2] == b"#!"
    except OSError:
        return False


def migrate_to_app() -> dict:
    """Install the standalone app (from the browser-based version) and open it."""
    rel = latest_release()
    if not rel["app_zip"]:
        raise UpdateError("The latest release doesn't include the Mac app yet")
    staged = _stage_app(rel)
    dest = applications_dir() / APP_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    old_launcher = config.home() / "Applications" / APP_NAME
    if old_launcher != dest and _is_legacy_launcher(old_launcher):
        shutil.rmtree(old_launcher)
    if dest.exists():
        if _is_legacy_launcher(dest):
            shutil.rmtree(dest)
        else:
            shutil.rmtree(_previous_app(), ignore_errors=True)
            _previous_app().parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), str(_previous_app()))
    shutil.move(str(staged), str(dest))
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(dest)], start_new_session=True)
    return {"to": rel["version"], "path": str(dest)}


def cleanup_legacy() -> None:
    """The standalone app removes what the old browser-based install left behind."""
    root = install_root()
    for name in ("versions", "current", "install.sh", ".current-new"):
        p = root / name
        try:
            if p.is_symlink() or p.is_file():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p)
        except OSError:
            pass
