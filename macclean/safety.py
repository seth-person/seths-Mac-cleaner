"""Shared guards for anything that moves or trashes files.

- protected_reason(): folders that must never be moved or trashed
  (top-level folders, everything directly in ~/Library, app data roots,
  sound libraries...)
- sound libraries: sample/instrument content that is never "junk", however
  old or duplicated it looks
- used_by_sets(): every file an Ableton set needs, so nothing it points at
  is ever suggested for the Trash
- preflight(): re-checks an item at the moment you click, because the scan
  may be out of date
- premove_problem(): checked right before every move or trash: the app that
  owns it isn't open, it stays on the same disk, and nothing only in iCloud
  leaves iCloud
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import unicodedata

from . import config


def norm(path: str) -> str:
    """Compare paths the way APFS does (case- and normalisation-insensitive)."""
    return unicodedata.normalize("NFD", os.path.normpath(path)).casefold()


# --- sound libraries ---------------------------------------------------------
LIBRARY_MARKERS = ("/factory packs/", "/core library/", "/user library/", "/splice/",
                   "/native instruments/", "/audio music apps/", "/spitfire audio/", "/eastwest/",
                   "/uvi/", "/kontakt/", "/packs/")
LIBRARY_EXTS = {".nkx", ".nkc", ".ncw", ".nicnt", ".nkr", ".nki", ".nkm", ".nkb", ".ark", ".ufs",
                ".ewi", ".zmulti", ".sbf", ".exs", ".sf2", ".sfz", ".alp", ".adg", ".adv", ".amxd"}


def library_roots() -> list:
    h = config.home()
    return [str(h / p) for p in ("Music/Ableton", "Splice", "Music/Splice", "Music/Logic", "Music/GarageBand",
                                 "Music/Audio Music Apps", "Music/Music", "Documents/Native Instruments")]


def in_sound_library(path: str) -> bool:
    n = norm(path) + "/"
    if any(m in n for m in LIBRARY_MARKERS):
        return True
    if os.path.splitext(path)[1].lower() in LIBRARY_EXTS:
        return True
    return any(n.startswith(norm(r) + "/") for r in library_roots())


# --- Ableton -----------------------------------------------------------------
def used_by_sets(con) -> dict:
    """norm(path) -> a set that uses it (every resolved reference, not just external ones)."""
    out = {}
    if con is None:
        return out
    for r in con.execute("SELECT ref_path, set_path FROM ableton_refs"):
        out.setdefault(norm(r["ref_path"]), r["set_path"])
    return out


class UsedIndex:
    """Which files and folders Ableton sets depend on. Build once per request:
    looking up a file or a folder is then a single dictionary hit."""

    def __init__(self, con):
        self.files = {}    # norm(file) -> set paths using it
        self.folders = {}  # norm(folder) -> set paths using something inside it
        if con is None:
            return
        for r in con.execute("SELECT ref_path, set_path FROM ableton_refs"):
            n = norm(r["ref_path"])
            self.files.setdefault(n, set()).add(r["set_path"])
            d = os.path.dirname(n)
            while d and d != os.path.dirname(d):
                self.folders.setdefault(d, set()).add(r["set_path"])
                d = os.path.dirname(d)

    def users(self, path: str) -> list:
        """Sets *outside* `path` that use it or anything inside it. (A project
        folder's own sets don't count: they move or go with it.)"""
        n = norm(path)
        sets = self.files.get(n, set()) | self.folders.get(n, set())
        return sorted(s for s in sets if not norm(s).startswith(n + "/"))


def project_dirs(con) -> list:
    if con is None:
        return []
    return [r["path"] for r in con.execute("SELECT path FROM dirs WHERE kind='ableton-project'")]


def inside_any(path: str, roots) -> bool:
    n = norm(path)
    return any(n.startswith(norm(r) + "/") for r in roots)


def unchecked_sets(con) -> list:
    """Sets and presets the scan couldn't read (only in iCloud, or damaged):
    what they use is unknown, so nothing may be called unused."""
    if con is None:
        return []
    return [dict(r) for r in con.execute("SELECT path, error FROM ableton_sets WHERE error IS NOT NULL "
                                         "UNION ALL SELECT path, error FROM ableton_presets WHERE error IS NOT NULL")]


# --- protected folders -------------------------------------------------------
_LIBRARY_DATA_ROOTS = ("Application Support", "Containers", "Group Containers", "Mobile Documents",
                       "CloudStorage", "Preferences", "Keychains", "Mail", "Messages", "Accounts",
                       "Calendars", "Safari", "Photos", "Audio")
_PROTECTED_SUFFIXES = (".photoslibrary", ".musiclibrary", ".tvlibrary", ".imovielibrary")


def protected_reason(path: str, cfg: dict) -> str | None:
    h = os.path.realpath(config.home())
    # A symlink is just a link: judge the link itself, not what it points at.
    real = os.path.join(os.path.realpath(os.path.dirname(os.path.abspath(path))), os.path.basename(path)) \
        if os.path.islink(path) else os.path.realpath(path)
    parent = os.path.dirname(real)
    lib = os.path.join(h, "Library")
    tops = {h, lib, *(os.path.join(h, d) for d in ("Desktop", "Downloads", "Documents", "Music", "Pictures",
                                                    "Movies", ".Trash", "Applications"))}
    tops.update(os.path.realpath(p) for p in config.inbox_paths(cfg))
    tops.add(os.path.realpath(config.expand(cfg["cloud_root"], cfg)))
    tops.add(os.path.realpath(config.expand(cfg["ableton_root"], cfg)))
    if cfg.get("library_ready"):
        lib_paths = config.library_paths(cfg)
        tops.update(os.path.realpath(lib_paths[k]) for k in ("root", "projects", "releases", "work", "samples"))
        tops.update(os.path.realpath(p) for p in lib_paths["statuses"].values())
    if real in tops:
        return "is a main folder"
    if parent == lib:
        return "holds macOS and app data"
    if parent == os.path.realpath(config.expand(cfg["cloud_root"], cfg)) and os.path.isdir(real):
        return "is a main folder in iCloud Drive"
    if any(parent == os.path.join(lib, d) for d in _LIBRARY_DATA_ROOTS):
        return "holds an app's settings or data"
    music_ableton = os.path.join(h, "Music", "Ableton")
    if real == music_ableton or parent == music_ableton:
        return "is part of Ableton's library"
    if real.lower().endswith(_PROTECTED_SUFFIXES):
        return "is a Photos/Music/TV library"
    if any(part.casefold() == "rekordbox" for part in real.split(os.sep)):
        return "is part of your rekordbox library, and moving it would break rekordbox's track paths"
    live = _live_reason(real)
    if live:
        return live
    return None


def _live_reason(real: str) -> str | None:
    """Live's User Library (and its main folders) and installed Packs are only
    ever moved or removed from inside Live: Live tracks where they are."""
    from . import live_prefs
    info = live_prefs.read_library()
    n = norm(real)
    if info and info.get("user_library"):
        ul = norm(os.path.realpath(info["user_library"]))
        if n == ul or os.path.dirname(n) == ul:
            return ("is part of Live's User Library. Move it from inside Live "
                    "(Settings → Library → Location of User Library), or projects that use it break")
    for folder in live_prefs.pack_folders(info):
        f = norm(os.path.realpath(folder))
        if n == f or os.path.dirname(n) == f:
            return "is an installed Live Pack. Remove it from Live's browser (Packs) instead"
    return None


def preflight(index: UsedIndex, path: str, action: str, scanned: dict | None = None) -> str | None:
    """Last check before a trash or move: nothing outside uses it, and it's
    still the same file the scan saw."""
    if action not in ("trash", "trash-asd", "move"):
        return None
    users = index.users(path)
    if users:
        verb = "moving" if action == "move" else "trashing"
        return (f"{os.path.basename(users[0])} uses {'it' if os.path.isfile(path) else 'files in it'}; "
                f"{verb} it would break that set")
    if action != "move" and scanned and os.path.isfile(path):
        try:
            st = os.stat(path)
        except OSError:
            return None
        if abs(st.st_mtime - scanned["mtime"]) > 2 or st.st_size != scanned["size"]:
            return "it changed since the last scan; rescan first"
    return None


# --- right before a move or trash ----------------------------------------------
SF_DATALESS = 0x40000000  # macOS: the file's contents live only in iCloud
CLOUD_CHECK_LIMIT = 50000  # entries walked when checking a folder for iCloud-only files

# Apps that keep track of where their files are, by process name.
APPS = {"Live": "Ableton Live", "Final Cut Pro": "Final Cut Pro", "rekordbox": "rekordbox"}
_running_cache = {}


def app_running(process: str) -> bool:
    """Whether a macOS app is open right now (checked at most every few seconds)."""
    if sys.platform != "darwin":
        return False
    hit = _running_cache.get(process)
    if hit and time.time() - hit[1] < 5:
        return hit[0]
    try:
        running = subprocess.run(["pgrep", "-xq", process], timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        running = False
    _running_cache[process] = (running, time.time())
    return running


def _in_project(path: str) -> bool:
    """The item is an Ableton project, a set, or something inside a project."""
    if path.lower().endswith(".als"):
        return True
    h = os.path.realpath(config.home())
    p = os.path.realpath(path) if not os.path.islink(path) else os.path.dirname(os.path.abspath(path))
    while p.startswith(h + os.sep):
        if os.path.isdir(os.path.join(p, "Ableton Project Info")):
            return True
        p = os.path.dirname(p)
    return False


def _contains_sets(path: str, limit: int = 2000) -> bool:
    """A folder that holds Ableton projects or sets (e.g. an EP's folder)."""
    if not os.path.isdir(path) or os.path.islink(path):
        return False
    n = 0
    for dirpath, dirnames, filenames in os.walk(path):
        if "Ableton Project Info" in dirnames or any(f.lower().endswith(".als") for f in filenames):
            return True
        n += len(dirnames) + len(filenames)
        if n > limit:
            return False
    return False


def cloud_only(path: str) -> bool:
    """True when the item (or anything in a folder) is only in iCloud, not on this Mac.
    A folder too big to check counts as having some, to be safe."""
    def dataless(p: str, name: str) -> bool:
        if name.startswith(".") and name.endswith(".icloud"):
            return True
        try:
            return bool(getattr(os.lstat(p), "st_flags", 0) & SF_DATALESS)
        except OSError:
            return False
    if not os.path.isdir(path) or os.path.islink(path):
        return dataless(path, os.path.basename(path))
    n = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for name in filenames + dirnames:
            n += 1
            if n > CLOUD_CHECK_LIMIT or dataless(os.path.join(dirpath, name), name):
                return True
    return False


def _existing_ancestor(path: str) -> str:
    p = os.path.abspath(path)
    while not os.path.exists(p) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    return p


def same_disk(src: str, dest_dir: str) -> bool:
    try:
        return os.lstat(src).st_dev == os.stat(_existing_ancestor(dest_dir)).st_dev
    except OSError:
        return False


def premove_problem(src: str, dest_dir: str, cfg: dict) -> str | None:
    """Why this move (or trash, with dest_dir = the Trash) can't happen right now, or None."""
    name = os.path.basename(src)
    if (_in_project(src) or _contains_sets(src)) and app_running("Live"):
        return f"Ableton Live is open. Close Live first, so it doesn't lose track of {name}"
    if src.lower().endswith(".fcpbundle") and app_running("Final Cut Pro"):
        return "Final Cut Pro is open. Close it before moving its library"
    if any(part.casefold() == "rekordbox" for part in os.path.abspath(src).split(os.sep)) and app_running("rekordbox"):
        return "rekordbox is open. Close it first"
    if not same_disk(src, dest_dir):
        return f"{name} would move to a different disk. Mac Cleaner only moves things within the same disk for now"
    cloud = os.path.realpath(config.expand(cfg["cloud_root"], cfg))
    leaving_cloud = (os.path.realpath(os.path.dirname(os.path.abspath(src))) + os.sep).startswith(cloud + os.sep) \
        and not (os.path.realpath(_existing_ancestor(dest_dir)) + os.sep).startswith(cloud + os.sep)
    if leaving_cloud and cloud_only(src):
        return (f"{name} has files that are only in iCloud. In Finder, right-click it and choose "
                "Download Now, wait for it to finish, then try again")
    return None
