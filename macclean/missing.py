"""Finding a project's missing files again. Read-only: Mac Cleaner never edits a set.

For every file a set can't find, it looks for files with the same name anywhere
the last scan saw, and suggests the folder to point Live's own search at
(File → Manage Files → Manage Set → Locate → Search Folder), so Live fixes them
all in one go. Files that can't come back say why: Google Drive is gone, a drive
isn't connected, or the path is from an older Mac.
"""
from __future__ import annotations

import os
from collections import defaultdict

from . import ableton, config, db, live_prefs, safety

GONE_FOLDERS = ("/My Drive/", "/Google Drive/", "/GoogleDrive")  # Google Drive no longer exists here
SUGGESTIONS = 3

_cache = {}


def _names(con) -> dict:
    """lower-case file name -> paths, for audio and Live devices, built once per scan."""
    key = tuple(sorted(db.meta(con).items()))
    hit = _cache.get("names")
    if hit and hit[0] == key:
        return hit[1]
    idx = defaultdict(list)
    for r in con.execute("SELECT name, path FROM files WHERE category='audio' OR ext IN "
                         "('.amxd', '.adg', '.adv', '.alc', '.agr')"):
        if "/.Trash/" in r["path"] or "/Backup/" in r["path"]:
            continue
        idx[r["name"].casefold()].append(r["path"])
    _cache["names"] = (key, idx)
    return idx


def why_gone(path: str) -> str | None:
    if not path:
        return None
    if any(g.casefold() in path.casefold() for g in GONE_FOLDERS):
        return "it was in Google Drive, which isn't on this Mac any more"
    if path.startswith("/Volumes/"):
        vol = path.split("/")[2]
        if not os.path.isdir("/Volumes/" + vol):
            return f"it was on a drive called “{vol}”, which isn't connected"
    if path.startswith("/Users/"):
        user = path.split("/")[2]
        if user != os.path.basename(str(config.home())):
            return f"the path is from an older Mac (user “{user}”)"
    return None


def _ancestors(path: str, stop: list) -> list:
    out = []
    d = os.path.dirname(path)
    for _ in range(4):
        if not d or any(d == s for s in stop):
            break
        out.append(d)
        d = os.path.dirname(d)
    return out


def suggest_folders(found: dict) -> list:
    """found: missing name -> candidate paths. Folders that cover the most names, best first."""
    home = str(config.home())
    stop = [home, os.path.join(home, config.ICLOUD_REL), os.path.dirname(home), "/"]
    left = set(found)
    out = []
    while left and len(out) < SUGGESTIONS:
        cover = defaultdict(set)
        for name in left:
            for p in found[name]:
                for a in _ancestors(p, stop):
                    cover[a].add(name)
        if not cover:
            break
        # most names covered, then the deepest (most specific) folder
        best = max(cover, key=lambda a: (len(cover[a]), a.count("/")))
        out.append({"folder": best, "covers": len(cover[best])})
        left -= cover[best]
    return out


def find_for_project(con, project: str) -> dict:
    if not os.path.isdir(project):
        raise FileNotFoundError(f"{project} isn't there any more")
    packs = live_prefs.installed_packs()
    names = _names(con) if con is not None else {}
    sets = []
    for s in ableton._sets_under(project):
        try:
            mtime = os.path.getmtime(s)
            res = ableton.check_set(s, project, packs)
        except Exception as e:
            sets.append({"set": s, "error": str(e), "items": []})
            continue
        items = []
        for ref in res["missing_refs"]:
            shown = ref["path"] or ref["rel"]
            name = os.path.basename(shown)
            cands = [p for p in names.get(name.casefold(), []) if not safety.norm(p).startswith(safety.norm(project) + "/")]
            items.append({"name": name, "was": shown, "where": ref.get("where") or "", "gone": why_gone(ref["path"]),
                          "candidates": cands[:5], "more": max(0, len(cands) - 5)})
        sets.append({"set": s, "mtime": mtime, "missing": len(items), "items": items,
                     "found": sum(1 for i in items if i["candidates"])})
    real = [s for s in sets if "error" not in s]
    if real:
        max(real, key=lambda s: s["mtime"])["newest"] = True
    found = {}
    for s in real:
        for i in s["items"]:
            if i["candidates"]:
                found.setdefault(i["name"], i["candidates"])
    all_items = [i for s in real for i in s["items"]]
    return {"project": project, "sets": sorted(sets, key=lambda s: -(s.get("mtime") or 0)),
            "missing": len({i["name"] for i in all_items}),
            "findable": len(found), "gone": len({i["name"] for i in all_items if i["gone"] and not i["candidates"]}),
            "folders": suggest_folders(found)}
