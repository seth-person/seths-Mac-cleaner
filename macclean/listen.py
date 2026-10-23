"""Hearing a set from Mac Cleaner.

A set (.als) holds no audio of its own, only instructions Live plays back
through your instruments and effects, and Live can't render one without
opening it. So we play audio that already exists:

  bounces      exports of the song, matched to each set by name: "Blackout
               Remix V10.wav" and "Blackout Remix (MASTER 24-bit 48k).wav"
               both belong to "Blackout Remix.als". Anywhere the scan saw
               them except inside Samples folders and sound libraries.
  ingredients  the audio files a set itself uses (samples, recordings,
               stems), from the dependency index.

Only files from the last scan are ever served for playback.
"""
from __future__ import annotations

import os
import re
import unicodedata
from collections import defaultdict

from . import db, safety

PLAYABLE = {".wav", ".wave", ".aif", ".aiff", ".aifc", ".mp3", ".flac", ".m4a", ".aac", ".caf", ".ogg"}
CONTENT_TYPES = {".wav": "audio/wav", ".wave": "audio/wav", ".aif": "audio/aiff", ".aiff": "audio/aiff",
                 ".aifc": "audio/aiff", ".mp3": "audio/mpeg", ".flac": "audio/flac", ".m4a": "audio/mp4",
                 ".aac": "audio/aac", ".caf": "audio/x-caf", ".ogg": "audio/ogg"}

_VERSION = re.compile(r"(?<![a-z0-9])v\s?(\d+(?:\.\d+)?)(?![a-z0-9])", re.I)
_BRACKETS = re.compile(r"[(\[{][^)\]}]*[)\]}]")
_NOISE = re.compile(r"(?<![a-z0-9])(?:master(?:ed)?|bounced?|exported|export|final|mixdown|rendered|render|preview"
                    r"|\d+\s?-?\s?bit|\d+(?:\.\d+)?\s?k(?:hz)?)(?![a-z0-9])", re.I)
MAX_BOUNCES = 6


def song_key(name: str) -> tuple:
    """('blackout remix', '10') for 'Blackout Remix V10 (MASTER 24-bit 48k).wav'."""
    stem = unicodedata.normalize("NFC", os.path.splitext(os.path.basename(name))[0])
    m = _VERSION.search(stem)
    s = _BRACKETS.sub(" ", stem)
    s = _VERSION.sub(" ", s)
    s = _NOISE.sub(" ", s)
    s = re.sub(r"[_\-.,]+", " ", s)
    s = " ".join(s.lower().split())
    if s.endswith(" project"):
        s = s[: -len(" project")]
    return s, (m.group(1) if m else None)


_index_cache = {}
_exports_cache = {}


def _bounce_index(con) -> dict:
    """song key -> exported audio files, built once per scan."""
    key = tuple(sorted(db.meta(con).items()))
    if key in _index_cache:
        return _index_cache[key]
    from . import config
    marker = "/" + ((config.load_config().get("layout") or {}).get("exports") or "Exports") + "/"
    idx, in_exports = defaultdict(list), defaultdict(list)
    for r in con.execute("SELECT path, name, ext, size, mtime, dataless FROM files WHERE category='audio'"):
        if r["ext"] not in PLAYABLE:
            continue
        p = r["path"]
        if "/Samples/" in p or "/Backup/" in p or "/.Trash/" in p or safety.in_sound_library(p):
            continue
        k, version = song_key(r["name"])
        b = {"path": p, "name": r["name"], "size": r["size"], "mtime": r["mtime"],
             "version": version, "icloud_only": bool(r["dataless"])}
        if marker in p and "/Stems/" not in p[p.rfind(marker):]:  # a project's own exports, whatever their name
            in_exports[p[: p.rfind(marker)]].append(b)
        if len(k) >= 2:
            idx[k].append(b)
    _index_cache.clear()
    _index_cache[key] = idx
    _exports_cache.clear()
    _exports_cache[key] = in_exports
    return idx


def _project_exports(con) -> dict:
    """project folder -> the audio in its Exports folder (not the stems)."""
    _bounce_index(con)
    return _exports_cache[tuple(sorted(db.meta(con).items()))]


def bounces_for(con, set_path: str, project_name: str | None = None, limit: int | None = MAX_BOUNCES,
                project_path: str | None = None) -> list:
    """Exports of the song a set makes, best match first: the same version
    number as the set (if it has one), then newest. With project_path, the
    project's own Exports folder counts too, even after a rename."""
    idx = _bounce_index(con)
    k, version = song_key(set_path)
    found = {b["path"]: b for b in idx.get(k, [])}
    if project_name:
        for b in idx.get(song_key(project_name)[0], []):
            found.setdefault(b["path"], b)
    if project_path:
        for b in _project_exports(con).get(project_path, []):
            found.setdefault(b["path"], b)
    ranked = sorted(found.values(), key=lambda b: (not (version and b["version"] == version), -(b["mtime"] or 0)))
    return ranked[:limit] if limit else ranked


def attach_bounces(con, projects: list, loose: list) -> None:
    """Add 'bounces' to every set in the Ableton overview."""
    for p in projects:
        for s in p["sets"]:
            newest = s["path"] == p.get("newest_set")
            s["bounces"] = bounces_for(con, s["path"], p["name"] if newest else None, project_path=p["path"] if newest else None)
    for s in loose:
        s["bounces"] = bounces_for(con, s["path"])


def ingredients(con, set_path: str, project: str | None) -> list:
    """The audio files a set uses, with where each one lives."""
    out, seen = [], set()
    for r in con.execute("SELECT ref_path FROM ableton_refs WHERE set_path=?", (set_path,)):
        p = r["ref_path"]
        if p in seen or os.path.splitext(p)[1].lower() not in PLAYABLE:
            continue
        seen.add(p)
        try:
            st = os.stat(p)
        except OSError:
            continue
        where = ("project" if project and safety.norm(p).startswith(safety.norm(project) + "/")
                 else "library" if safety.in_sound_library(p) else "elsewhere")
        out.append({"path": p, "name": os.path.basename(p), "size": st.st_size, "where": where})
    return sorted(out, key=lambda x: (x["where"] != "project", x["name"].lower()))


def playable(con, path: str) -> bool:
    """Only audio the last scan knows about: an exported file, or one a set uses."""
    if not isinstance(path, str) or os.path.splitext(path)[1].lower() not in PLAYABLE or not os.path.isfile(path):
        return False
    return bool(con.execute("SELECT 1 FROM files WHERE path=? AND category='audio'", (path,)).fetchone()
                or con.execute("SELECT 1 FROM ableton_refs WHERE ref_path=? LIMIT 1", (path,)).fetchone())
