"""Files that are only in iCloud, the setting that makes more of them, and the
two ways to keep them on this Mac.

With Optimise Mac Storage on, macOS removes the local copy of iCloud files
(iCloud Drive, and Desktop and Documents when they sync) you haven't opened
lately whenever this Mac wants the space. The file stays in iCloud and
downloads again when something opens it, so Live waits on the download (or
reports the sample missing when you're offline).

  Keep Downloaded  the same setting as Finder's right-click → Keep Downloaded:
                   macOS downloads everything in the folder and never removes
                   it again. It's a mark on the folder (an extended attribute),
                   and a folder inside a kept folder is kept too. Each change
                   is checked with File Provider (`fileproviderctl evaluate`),
                   the part of macOS that syncs these folders.
  Download now     opens each file that's only in iCloud, which makes macOS
                   download it. It runs in the background; macOS may remove
                   the files again later unless they're kept downloaded.

Nothing else is written: reading the setting, the disk, and which files the
last scan saw only in iCloud is all read-only.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import itertools
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import config, safety

LOW_FREE_BYTES = 30e9   # below this macOS removes local copies more eagerly
LOW_FREE_SHARE = 0.10
MIN_FREE_AFTER = 10e9   # Download now leaves at least this much free
KEEP_ATTR = b"com.apple.fileprovider.pinned#PX"  # what Finder's Keep Downloaded sets
KEEP_VALUE = b"1"
XATTR_NOFOLLOW = 0x0001
DOWNLOAD_THREADS = 4
MUSIC_CATEGORIES = ("audio", "ableton", "plugin")

_cache = {}
_lock = threading.Lock()
_jobs = {}
_ids = itertools.count(1)


def optimise_storage() -> bool | None:
    """True when Optimise Mac Storage is on, None when it can't be told."""
    hit = _cache.get("optimise")
    if hit and time.time() - hit[1] < 60:
        return hit[0]
    value = None
    if sys.platform == "darwin":
        try:
            r = subprocess.run(["defaults", "read", "com.apple.bird", "optimize-storage"],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip() in ("0", "1"):
                value = r.stdout.strip() == "1"
        except (OSError, subprocess.SubprocessError):
            pass
    _cache["optimise"] = (value, time.time())
    return value


def disk() -> dict:
    try:
        u = shutil.disk_usage(str(config.home()))
    except OSError:
        return {"free": None, "total": None, "low": False}
    return {"free": u.free, "total": u.total,
            "low": u.free < LOW_FREE_BYTES or u.free < u.total * LOW_FREE_SHARE}


def _st_cloud_only(st) -> bool:
    return bool(getattr(st, "st_flags", 0) & safety.SF_DATALESS)


def is_cloud_only(path: str) -> bool:
    try:
        return _st_cloud_only(os.lstat(path))
    except OSError:
        return False


# --- Keep Downloaded -----------------------------------------------------------
def _libc():
    if "libc" not in _cache:
        c = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        c.getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        c.getxattr.restype = ctypes.c_ssize_t
        c.setxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        c.removexattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        _cache["libc"] = c
    return _cache["libc"]


def is_kept(path: str) -> bool:
    """Is Keep Downloaded set on this folder itself?"""
    if sys.platform != "darwin":
        return False
    buf = ctypes.create_string_buffer(16)
    n = _libc().getxattr(os.fsencode(path), KEEP_ATTR, buf, 16, 0, XATTR_NOFOLLOW)
    return n > 0 and buf.raw[:n].strip(b"\0 ") == KEEP_VALUE


def kept_by(path: str, cache: dict | None = None) -> str | None:
    """The folder whose Keep Downloaded covers `path`: itself or one it's inside."""
    home = str(config.home())
    p = os.path.abspath(path)
    while p.startswith(home + os.sep):
        if cache is None or p not in cache:
            hit = is_kept(p)
            if cache is not None:
                cache[p] = hit
        else:
            hit = cache[p]
        if hit:
            return p
        p = os.path.dirname(p)
    return None


def _evaluate(path: str) -> dict | None:
    """File Provider's view of an item ({'isKeepDownloaded': '1', ...}), or None
    when File Provider doesn't sync it (not in iCloud)."""
    if sys.platform != "darwin":
        return None
    try:
        r = subprocess.run(["fileproviderctl", "evaluate", path], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if "fileproviderItems" not in (r.stdout or ""):
        return None
    return dict(re.findall(r"^\s*(\w+) = ([^;{(]*);\s*$", r.stdout, re.M))


def _problem(path: str) -> str | None:
    home = str(config.home())
    if not os.path.isabs(path) or not os.path.exists(path):
        return "That isn't there any more. Rescan first."
    if not path.startswith(home + os.sep):
        return "Only folders in your home folder"
    if path in (os.path.join(home, "Library"), os.path.join(home, "Library", "Mobile Documents")):
        return "Pick a folder inside it instead"
    return None


def keep_downloaded(path: str, on: bool) -> dict:
    """Turn Keep Downloaded on or off for one folder or file, like Finder does."""
    path = os.path.abspath(os.path.expanduser(path))
    problem = _problem(path)
    if problem:
        raise ValueError(problem)
    if _evaluate(path) is None:
        raise ValueError("That isn't synced with iCloud, so it's always on this Mac")
    if not on and not is_kept(path):
        by = kept_by(path)
        raise ValueError(f"It's kept because {os.path.basename(by)} is. Change it there." if by else "It isn't kept downloaded")
    c = _libc()
    if on:
        rc = c.setxattr(os.fsencode(path), KEEP_ATTR, KEEP_VALUE, len(KEEP_VALUE), 0, XATTR_NOFOLLOW)
    else:
        rc = c.removexattr(os.fsencode(path), KEEP_ATTR, XATTR_NOFOLLOW)
    if rc != 0:
        e = ctypes.get_errno()
        if on or e != getattr(errno, "ENOATTR", 93):  # turning off something already off is fine
            raise ValueError(f"macOS didn't allow it ({os.strerror(e)}). Use Finder: right-click → Keep Downloaded.")
    state = None
    for _ in range(10):  # File Provider picks the change up within a moment
        state = (_evaluate(path) or {}).get("isKeepDownloaded")
        if state == ("1" if on else "0"):
            break
        time.sleep(0.3)
    return {"kept": on, "confirmed": state == ("1" if on else "0"), "kept_by": kept_by(path)}


# --- Download now --------------------------------------------------------------
def _cloud_only_files(paths: list) -> list:
    out = []
    for root in paths:
        if os.path.isfile(root):
            if is_cloud_only(root):
                out.append((root, os.lstat(root).st_size))
            continue
        for dirpath, dirnames, filenames in os.walk(root):  # listing a folder fetches its contents' names
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for f in filenames:
                p = os.path.join(dirpath, f)
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                if _st_cloud_only(st):
                    out.append((p, st.st_size))
    return out


def _fetch(path: str) -> None:
    """Opening a file that's only in iCloud makes macOS download it."""
    with open(path, "rb") as f:
        f.read(1)
        if is_cloud_only(path):  # only part of it came down: read it all
            while f.read(1 << 20):
                pass


def download(paths: list, label: str = "") -> dict:
    """Start downloading everything only in iCloud under `paths`. Returns the job."""
    paths = [os.path.abspath(os.path.expanduser(p)) for p in paths if isinstance(p, str)]
    if not paths:
        raise ValueError("Pick something to download")
    for p in paths:
        problem = _problem(p)
        if problem:
            raise ValueError(problem)
    files = _cloud_only_files(paths)
    need = sum(s for _, s in files)
    free = disk()["free"]
    if free is not None and need > free - MIN_FREE_AFTER:
        raise ValueError(f"That's {need / 1e9:.1f} GB to download and only {free / 1e9:.1f} GB is free. Make room first.")
    job = {"id": next(_ids), "label": label or os.path.basename(paths[0]), "paths": paths, "files": len(files),
           "bytes": need, "done": 0, "done_bytes": 0, "errors": [], "started": time.time(), "finished": None,
           "cancelled": False}
    with _lock:
        _jobs[job["id"]] = job
        for old in sorted(_jobs)[:-10]:
            if _jobs[old]["finished"]:
                del _jobs[old]

    def one(item):
        path, size = item
        if job["cancelled"]:
            return
        try:
            _fetch(path)
        except OSError as e:
            with _lock:
                job["errors"].append(f"{os.path.basename(path)}: {e.strerror or e}")
            return
        with _lock:
            job["done"] += 1
            job["done_bytes"] += size

    def run():
        with ThreadPoolExecutor(DOWNLOAD_THREADS) as pool:
            list(pool.map(one, files))
        job["finished"] = time.time()
    threading.Thread(target=run, daemon=True).start()
    return dict(job)


def cancel(job_id: int) -> bool:
    job = _jobs.get(job_id)
    if job and not job["finished"]:
        job["cancelled"] = True
        return True
    return False


def jobs() -> list:
    with _lock:
        return [dict(j, errors=j["errors"][:5]) for j in sorted(_jobs.values(), key=lambda j: -j["id"])]


# --- what the dashboard shows ----------------------------------------------------
def attach(con, projects: list) -> None:
    """Add 'cloud_only' ({files, bytes, sets}) and 'kept_by' to each project in the Ableton overview."""
    by_path = {p["path"]: p for p in projects}
    cache = {}
    for p in projects:
        p["cloud_only"] = None
        p["kept_by"] = kept_by(p["path"], cache)
    for r in con.execute("SELECT path, size, ext FROM files WHERE dataless=1"):
        d = os.path.dirname(r["path"])
        while d and d != os.path.dirname(d) and d not in by_path:
            d = os.path.dirname(d)
        p = by_path.get(d)
        if p is None:
            continue
        c = p["cloud_only"] or {"files": 0, "bytes": 0, "sets": 0}
        c["files"] += 1
        c["bytes"] += r["size"] or 0
        c["sets"] += r["ext"] == ".als"
        p["cloud_only"] = c


def _area(path: str, home: str, cloud: str) -> str:
    """The folder to show a file under: one level inside iCloud Drive, Desktop or Documents."""
    for base in (cloud, os.path.join(home, "Desktop"), os.path.join(home, "Documents"),
                 os.path.join(home, "Library", "Mobile Documents")):
        if path.startswith(base + os.sep):
            first = path[len(base) + 1:].split(os.sep)[0]
            return os.path.join(base, first) if os.sep in path[len(base) + 1:] else base
    return os.path.dirname(path)


def areas(con, cfg: dict, limit: int = 12) -> list:
    """Where the files only in iCloud are (an Ableton project, or a folder one level
    inside iCloud Drive, Desktop or Documents), music first, then biggest."""
    home = str(config.home())
    cloud = str(config.expand(cfg.get("cloud_root") or config.DEFAULT_CONFIG["cloud_root"], cfg))
    try:
        projects = {r["path"] for r in con.execute("SELECT path FROM dirs WHERE kind='ableton-project'")}
    except Exception:  # no dirs table
        projects = set()
    out = {}
    for r in con.execute("SELECT path, size, category FROM files WHERE dataless=1"):
        d = os.path.dirname(r["path"])
        while d.startswith(home + os.sep) and d not in projects:
            d = os.path.dirname(d)
        a = out.setdefault(d if d in projects else _area(r["path"], home, cloud), {"files": 0, "bytes": 0, "music": False})
        a["files"] += 1
        a["bytes"] += r["size"] or 0
        a["music"] = a["music"] or r["category"] in MUSIC_CATEGORIES or safety.in_sound_library(r["path"])
    cache = {}
    rows = [{"path": p, **a, "kept_by": kept_by(p, cache)} for p, a in out.items()]
    return sorted(rows, key=lambda a: (not a["music"], -a["bytes"]))[:limit]


def kept_folders(cfg: dict) -> list:
    """Folders with Keep Downloaded set: in iCloud Drive, Desktop and Documents, two levels down."""
    home = str(config.home())
    cloud = str(config.expand(cfg.get("cloud_root") or config.DEFAULT_CONFIG["cloud_root"], cfg))
    out = []
    for base in (cloud, os.path.join(home, "Desktop"), os.path.join(home, "Documents")):
        if is_kept(base):
            out.append(base)
            continue
        try:
            for e in os.scandir(base):
                if e.is_dir(follow_symlinks=False) and not e.name.startswith(".") and is_kept(e.path):
                    out.append(e.path)
        except OSError:
            pass
    return out


def status(con, cfg: dict | None = None, projects: list | None = None) -> dict:
    """For the notices: the setting, the disk, how much is only in iCloud and where."""
    cfg = cfg or config.load_config()
    row = con.execute("SELECT COUNT(*) n, SUM(size) b FROM files WHERE dataless=1").fetchone() if con else None
    out = {"optimise": optimise_storage(), "disk": disk(),
           "cloud_only_files": row["n"] if row else 0, "cloud_only_bytes": (row["b"] or 0) if row else 0,
           "areas": areas(con, cfg) if con else [], "kept": kept_folders(cfg)}
    if projects is not None:
        hit = [p for p in projects if p.get("cloud_only")]
        out["projects"] = len(hit)
        out["project_paths"] = [p["path"] for p in hit]
        out["important"] = sorted((p["name"] for p in hit if p.get("important")), key=str.lower)
    return out
