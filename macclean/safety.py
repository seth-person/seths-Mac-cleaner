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
"""
from __future__ import annotations

import os
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


def project_dirs(con) -> list:
    if con is None:
        return []
    return [r["path"] for r in con.execute("SELECT path FROM dirs WHERE kind='ableton-project'")]


def inside_any(path: str, roots) -> bool:
    n = norm(path)
    return any(n.startswith(norm(r) + "/") for r in roots)


def unchecked_sets(con) -> list:
    """Sets the scan couldn't read (only in iCloud, or damaged): their samples are unknown."""
    if con is None:
        return []
    return [dict(r) for r in con.execute("SELECT path, error FROM ableton_sets WHERE error IS NOT NULL")]


# --- protected folders -------------------------------------------------------
_LIBRARY_DATA_ROOTS = ("Application Support", "Containers", "Group Containers", "Mobile Documents",
                       "CloudStorage", "Preferences", "Keychains", "Mail", "Messages", "Accounts",
                       "Calendars", "Safari", "Photos", "Audio")
_PROTECTED_SUFFIXES = (".photoslibrary", ".musiclibrary", ".tvlibrary", ".imovielibrary")


def protected_reason(path: str, cfg: dict) -> str | None:
    h = os.path.realpath(config.home())
    real = os.path.realpath(path)
    parent = os.path.dirname(real)
    lib = os.path.join(h, "Library")
    tops = {h, lib, *(os.path.join(h, d) for d in ("Desktop", "Downloads", "Documents", "Music", "Pictures",
                                                    "Movies", ".Trash", "Applications"))}
    tops.update(os.path.realpath(p) for p in config.inbox_paths(cfg))
    tops.add(os.path.realpath(config.expand(cfg["cloud_root"], cfg)))
    tops.add(os.path.realpath(config.expand(cfg["ableton_root"], cfg)))
    if real in tops:
        return "is a main folder"
    if parent == lib:
        return "holds macOS and app data"
    if any(parent == os.path.join(lib, d) for d in _LIBRARY_DATA_ROOTS):
        return "holds an app's settings or data"
    music_ableton = os.path.join(h, "Music", "Ableton")
    if real == music_ableton or parent == music_ableton:
        return "is part of Ableton's library"
    if real.lower().endswith(_PROTECTED_SUFFIXES):
        return "is a Photos/Music/TV library"
    return None


def preflight(con, path: str, action: str, scanned: dict | None = None) -> str | None:
    """Last check before trashing: still the same file, and nothing uses it?"""
    if action not in ("trash", "trash-asd"):
        return None
    used = used_by_sets(con)
    if norm(path) in used:
        return f"an Ableton set uses it ({os.path.basename(used[norm(path)])})"
    if scanned and os.path.isfile(path):
        try:
            st = os.stat(path)
        except OSError:
            return None
        if abs(st.st_mtime - scanned["mtime"]) > 2 or st.st_size != scanned["size"]:
            return "it changed since the last scan; rescan first"
    return None
