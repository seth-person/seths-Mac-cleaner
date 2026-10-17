"""Ableton Live project discovery and set (.als) dependency checks.

An .als file is gzipped XML. Every sample/device file the set needs appears as
a <FileRef> holding an absolute <Path> and a <RelativePath> (Live 10+), or a
list of <RelativePathElement Dir=".."/> plus <Name> (Live 9). For each set we
check where each referenced file resolves:

  in_project - inside the project folder: moves with it (what Collect All does)
  packs      - Ableton factory content / installed Packs: fine on this Mac
  external   - exists but outside the project: breaks if the project moves
               to another machine, or the outside file is moved/deleted
  missing    - can't be found at all (already broken)

FileRefs that only record *where a sample originally came from* (browser
history, presets last loaded) aren't needed for playback and are ignored.
"""
from __future__ import annotations

import gzip
import json
import os
import zlib
from collections import defaultdict
from xml.parsers import expat

from . import config

_IGNORED_CONTEXTS = {"SourceContext", "OriginalFileRef", "LastPresetRef", "PresetRef",
                     "BrowserContentPath", "OriginalFileSize"}
_PACK_MARKERS = ("/Factory Packs/", "/Core Library/", "/Ableton/Packs/", "/App-Resources/")


def parse_set(path: str) -> dict:
    """Return {'version': str, 'refs': [{'path','rel','pack'}]} for an .als file."""
    refs = []
    version = ""
    stack = []
    cur = None

    def start(tag, attrs):
        nonlocal cur, version
        if not stack and tag == "Ableton":
            version = attrs.get("Creator", "")
        stack.append(tag)
        if tag == "FileRef" and cur is None and not _IGNORED_CONTEXTS.intersection(stack):
            cur = {"path": "", "rel": "", "rel_parts": [], "name": "", "pack": "", "depth": len(stack)}
            return
        if cur is None:
            return
        parent = stack[-2] if len(stack) > 1 else ""
        value = attrs.get("Value")
        if tag == "Path" and parent == "FileRef" and value:
            cur["path"] = value
        elif tag == "RelativePath" and value:
            cur["rel"] = value
        elif tag == "RelativePathElement":
            cur["rel_parts"].append(attrs.get("Dir", "") or "..")
        elif tag == "Name" and parent == "FileRef" and value:
            cur["name"] = value
        elif tag == "LivePackName" and value:
            cur["pack"] = value

    def end(tag):
        nonlocal cur
        if cur is not None and tag == "FileRef" and len(stack) == cur["depth"]:
            rel = cur["rel"]
            if not rel and (cur["rel_parts"] or cur["name"]):
                rel = "/".join(cur["rel_parts"] + ([cur["name"]] if cur["name"] else []))
            if rel or cur["path"]:
                refs.append({"path": cur["path"], "rel": rel, "pack": cur["pack"]})
            cur = None
        stack.pop()

    parser = expat.ParserCreate()
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        with gzip.open(path, "rb") as f:
            parser.ParseFile(f)
    except (OSError, EOFError, zlib.error):
        # Not gzipped (very old or hand-exported sets): try plain XML.
        parser = expat.ParserCreate()
        parser.StartElementHandler = start
        parser.EndElementHandler = end
        refs.clear()
        stack.clear()
        cur = None
        with open(path, "rb") as f:
            parser.ParseFile(f)
    return {"version": version, "refs": refs}


def _inside(path: str, folder: str) -> bool:
    return os.path.normpath(path).startswith(os.path.normpath(folder) + os.sep)


def check_set(path: str, project_dir: str | None) -> dict:
    parsed = parse_set(path)
    base = project_dir or os.path.dirname(path)
    counts = {"in_project": 0, "packs": 0, "external": 0, "missing": 0}
    examples = {"external": [], "missing": []}
    external = []
    used = []  # every file that resolved, wherever it is
    seen = set()
    for ref in parsed["refs"]:
        key = (ref["path"], ref["rel"])
        if key in seen:
            continue
        seen.add(key)
        candidates = []
        if ref["rel"]:
            candidates.append(os.path.normpath(os.path.join(base, ref["rel"])))
            candidates.append(os.path.normpath(os.path.join(os.path.dirname(path), ref["rel"])))
        if ref["path"]:
            candidates.append(ref["path"])
        found = next((c for c in candidates if os.path.exists(c)), None)
        shown = ref["path"] or ref["rel"]
        is_pack = bool(ref["pack"]) or any(m in shown for m in _PACK_MARKERS)
        if found:
            used.append(found)
        if found and _inside(found, base):
            counts["in_project"] += 1
        elif is_pack:
            counts["packs"] += 1
        elif found:
            counts["external"] += 1
            external.append(found)
            if len(examples["external"]) < 8:
                examples["external"].append(found)
        else:
            counts["missing"] += 1
            if len(examples["missing"]) < 8:
                examples["missing"].append(shown)
    return {"version": parsed["version"], "refs": len(seen), **counts, "examples": examples,
            "external_paths": external, "used_paths": used}


def _project_for(path: str, projects: set) -> str | None:
    d = os.path.dirname(path)
    while d and d != os.path.dirname(d):
        if d in projects:
            return d
        d = os.path.dirname(d)
    return None


def _is_backup(path: str) -> bool:
    return os.sep + "Backup" + os.sep in path


def analyse_sets(con, cfg, cancel=None, state=None) -> None:
    """Parse every current (non-backup) set found by the scan; store results."""
    projects = {r["path"] for r in con.execute("SELECT path FROM dirs WHERE kind='ableton-project'")}
    rows, ref_rows = [], []
    for r in con.execute("SELECT path, dataless FROM files WHERE ext='.als'").fetchall():
        if cancel is not None and cancel.is_set():
            break
        path = r["path"]
        if _is_backup(path) or os.path.basename(path).startswith("._"):
            continue
        project = _project_for(path, projects)
        if r["dataless"]:
            rows.append((path, project, "", 0, 0, 0, 0, 0, "{}", "Only in iCloud (not downloaded)"))
            continue
        try:
            res = check_set(path, project)
            rows.append((path, project, res["version"], res["refs"], res["in_project"], res["packs"],
                         res["external"], res["missing"], json.dumps(res["examples"]), None))
            ref_rows.extend((path, os.path.normpath(e)) for e in res["used_paths"])
        except Exception as e:  # corrupt/unreadable sets shouldn't stop the scan
            rows.append((path, project, "", 0, 0, 0, 0, 0, "{}", f"Couldn't read: {e}"))
        if state is not None:
            state["current"] = path
    con.executemany("INSERT OR REPLACE INTO ableton_sets VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.executemany("INSERT INTO ableton_refs VALUES (?,?)", ref_rows)
    con.commit()


def overview(con, cfg) -> dict:
    """Everything the Music tab needs."""
    root = str(config.expand(cfg["ableton_root"], cfg))
    buckets = cfg.get("ableton_buckets", [])
    sets_by_project = defaultdict(list)
    loose = []
    for r in con.execute("SELECT * FROM ableton_sets"):
        d = dict(r)
        d["examples"] = json.loads(d["examples"] or "{}")
        d["version"] = d.pop("live_version")
        if d["project"]:
            sets_by_project[d["project"]].append(d)
        else:
            loose.append(d)

    project_paths = {r["path"] for r in con.execute("SELECT path FROM dirs WHERE kind='ableton-project'")}
    sub = defaultdict(lambda: {"backup": 0, "asd": 0, "nbackups": 0, "newest": 0.0})
    for r in con.execute("SELECT path, alloc FROM dirs WHERE name='Backup'"):
        if r["path"][: -len("/Backup")] in project_paths:
            sub[r["path"][: -len("/Backup")]]["backup"] = r["alloc"]
    for r in con.execute("SELECT path, ext, alloc, mtime FROM files WHERE ext IN ('.asd', '.als')"):
        proj = _project_for(r["path"], project_paths)
        if not proj:
            continue
        if r["ext"] == ".asd":
            sub[proj]["asd"] += r["alloc"]
        elif _is_backup(r["path"]):
            sub[proj]["nbackups"] += 1
        else:
            sub[proj]["newest"] = max(sub[proj]["newest"], r["mtime"])

    projects = []
    names = defaultdict(list)
    for r in con.execute("SELECT * FROM dirs WHERE kind='ableton-project' ORDER BY mtime DESC"):
        p = r["path"]
        sets = sets_by_project.get(p, [])
        in_lib = _inside(p, root)
        bucket = None
        if in_lib:
            first = os.path.relpath(p, root).split(os.sep)[0]
            bucket = first if first in buckets else None
        status = _status(sets)
        extra = sub.get(p, {})
        item = {
            "path": p, "name": r["name"], "parent": r["parent"], "size": r["size"], "alloc": r["alloc"],
            "files": r["files"], "mtime": extra.get("newest") or r["mtime"], "in_library": in_lib, "bucket": bucket,
            "sets": [{k: s[k] for k in ("path", "version", "refs", "in_project", "packs", "external",
                                        "missing", "examples", "error")} for s in sets],
            "status": status, "backup_bytes": extra.get("backup") or 0,
            "backup_sets": extra.get("nbackups") or 0, "asd_bytes": extra.get("asd") or 0,
            "version": max((s["version"] for s in sets), default=""),
        }
        projects.append(item)
        names[_base_name(r["name"])].append(p)
    projects.sort(key=lambda x: -(x["mtime"] or 0))

    for item in projects:
        twins = [q for q in names[_base_name(item["name"])] if q != item["path"]]
        item["possible_copies"] = twins

    locations = defaultdict(lambda: {"count": 0, "alloc": 0})
    for item in projects:
        loc = "Projects folder · " + (item["bucket"] or "unsorted") if item["in_library"] else item["parent"]
        locations[loc]["count"] += 1
        locations[loc]["alloc"] += item["alloc"] or 0

    return {
        "root": root, "buckets": buckets, "projects": projects, "loose_sets": loose,
        "locations": sorted(({"location": k, **v} for k, v in locations.items()),
                            key=lambda x: -x["count"]),
        "totals": {
            "projects": len(projects),
            "outside_library": sum(1 for p in projects if not p["in_library"]),
            "needs_collect": sum(1 for p in projects if p["status"] in ("external", "missing")),
            "backup_bytes": sum(p["backup_bytes"] for p in projects),
            "asd_bytes": sum(p["asd_bytes"] for p in projects),
            "alloc": sum(p["alloc"] or 0 for p in projects),
        },
    }


def _base_name(name: str) -> str:
    n = name.lower().strip()
    changed = True
    while changed:
        changed = False
        for suffix in (" project", " copy", " (1)", " (2)", " (3)", " 2", " 3"):
            if n.endswith(suffix):
                n = n[: -len(suffix)].strip()
                changed = True
    return n


def _status(sets: list) -> str:
    if not sets:
        return "no-sets"
    if any(s["missing"] for s in sets):
        return "missing"
    if any(s["external"] for s in sets):
        return "external"
    if any(s["error"] for s in sets):
        return "unknown"
    return "ok"
