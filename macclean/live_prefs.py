"""Read-only access to Ableton Live's own settings.

Live keeps its library settings in
  ~/Library/Preferences/Ableton/Live <version>/Library.cfg
(plain XML). We read, never write, it:

  UserLibrary/LibraryProject  ProjectPath + ProjectName = the User Library
  SliceInfoList               installed Packs: Path, DisplayName, UniqueId
  UserFolderInfoList          the browser's Places
  DefaultTemplateSet          the default set new sets start from
  SpliceDownloadFolderModeMember / CustomSpliceDownloadPathMember
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from xml.etree import ElementTree

from . import config

_cache = {}


def prefs_root() -> Path:
    return config.home() / "Library" / "Preferences" / "Ableton"


def _version_key(name: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", name)[:4])


def library_cfg_path() -> Path | None:
    """Library.cfg of the newest Live version on this Mac."""
    root = prefs_root()
    try:
        dirs = [d for d in root.iterdir() if d.name.startswith("Live ") and (d / "Library.cfg").is_file()]
    except OSError:
        return None
    if not dirs:
        return None
    return max(dirs, key=lambda d: _version_key(d.name)) / "Library.cfg"


def _clean_id(value: str) -> str:
    # Pasted copies can turn "www.ableton.com/1" into "[www.ableton.com/1](https://…)".
    m = re.match(r"^\[([^\]]+)\]\([^)]*\)(.*)$", value or "")
    return (m.group(1) + m.group(2)) if m else (value or "")


def read_library() -> dict | None:
    """Parsed Library.cfg (cached until the file changes), or None if Live isn't set up here."""
    path = library_cfg_path()
    if path is None:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = (str(path), mtime)
    if key in _cache:
        return _cache[key]
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError):
        return None
    lib = root.find("ContentLibrary")
    if lib is None:
        return None

    def value(xpath):
        el = lib.find(xpath)
        return el.get("Value") if el is not None else None

    user_library = None
    proj = lib.find("UserLibrary/LibraryProject")
    if proj is not None:
        parent = (proj.find("ProjectPath").get("Value") if proj.find("ProjectPath") is not None else "") or ""
        name = (proj.find("ProjectName").get("Value") if proj.find("ProjectName") is not None else "") or ""
        if parent and name:
            user_library = os.path.join(parent, name)
    packs = [{"name": el.get("DisplayName") or os.path.basename(el.get("Path", "")), "path": el.get("Path", ""),
              "id": _clean_id(el.get("UniqueId", ""))}
             for el in lib.findall("SliceInfoList/LibrarySliceInfo") if el.get("Path")]
    places = [{"name": el.get("DisplayName") or os.path.basename(el.get("Path", "")), "path": el.get("Path", "")}
              for el in lib.findall("UserFolderInfoList/UserFolderInfo") if el.get("Path")]
    info = {
        "cfg_path": str(path),
        "live": root.get("Creator", ""),
        "user_library": user_library,
        "packs": packs,
        "places": places,
        "default_template": value("DefaultTemplateSet") or None,
        "packs_install_path": value("PreferredFactoryPacksInstallationPath") or None,
        "splice_mode": value("SpliceDownloadFolderModeMember"),
        "splice_path": value("CustomSpliceDownloadPathMember") or None,
    }
    _cache.clear()
    _cache[key] = info
    return info


def default_packs_dir() -> str:
    return str(config.home() / "Music" / "Ableton" / "Factory Packs")


def installed_packs(info: dict | None = None) -> list:
    """Packs Live lists, plus Pack folders on disk it doesn't list.
    [{name, path, id, listed, exists}]"""
    info = read_library() if info is None else info
    out, seen = [], set()
    for p in (info or {}).get("packs", []):
        out.append({**p, "listed": True, "exists": os.path.isdir(p["path"])})
        seen.add(os.path.normpath(p["path"]))
    folders = {default_packs_dir()}
    if info and info.get("packs_install_path"):
        folders.add(os.path.join(info["packs_install_path"], "Factory Packs"))
    folders.update(os.path.dirname(p["path"]) for p in out)
    for folder in sorted(folders):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for n in names:
            full = os.path.join(folder, n)
            if n.startswith(".") or not os.path.isdir(full) or os.path.normpath(full) in seen:
                continue
            seen.add(os.path.normpath(full))
            out.append({"name": n, "path": full, "id": "", "listed": False, "exists": True})
    return out


def pack_folders(info: dict | None = None) -> list:
    """Every folder that holds installed Packs (usually ~/Music/Ableton/Factory Packs)."""
    return sorted({os.path.dirname(p["path"]) for p in installed_packs(info)} | {default_packs_dir()})


# Paths of sets Live recently opened. Live keeps its recent-documents list in
# Preferences.cfg (a binary file) as text; we pick out every absolute path to an
# .als, in the order Live stores them (most recent first), whichever text
# encoding it used.
_UTF16_ALS = re.compile(rb"/\x00(?:[^\x00-\x1f]\x00|[\x00-\xff][\x01-\xff]){1,500}?\.\x00a\x00l\x00s\x00")
_UTF8_ALS = re.compile(rb"/[^\x00-\x1f]{1,1000}?\.als")


def recent_sets() -> list:
    """Absolute .als paths Live lists as recently opened (most recent first)."""
    cfg = library_cfg_path()
    root = cfg.parent if cfg else None
    if root is None:
        try:
            dirs = [d for d in prefs_root().iterdir() if d.name.startswith("Live ")]
        except OSError:
            return []
        if not dirs:
            return []
        root = max(dirs, key=lambda d: _version_key(d.name))
    try:
        data = (root / "Preferences.cfg").read_bytes()
    except OSError:
        return []
    found = []
    for m in _UTF16_ALS.finditer(data):
        try:
            found.append((m.start(), m.group().decode("utf-16-le")))
        except UnicodeDecodeError:
            pass
    for m in _UTF8_ALS.finditer(data):
        try:
            found.append((m.start(), m.group().decode("utf-8")))
        except UnicodeDecodeError:
            pass
    out, seen = [], set()
    for _, p in sorted(found):
        if p.startswith("/") and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def pinned_folders(info: dict | None = None) -> list:
    """Folders pinned in the Places section of Live's browser."""
    info = read_library() if info is None else info
    return [p["path"] for p in (info or {}).get("places") or [] if p.get("path")]


def template_problem(info: dict | None = None) -> str | None:
    """Live's default template points at a file that isn't there (new sets then start empty)."""
    info = read_library() if info is None else info
    t = (info or {}).get("default_template")
    if t and not os.path.exists(t):
        return t
    return None
