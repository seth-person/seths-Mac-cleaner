"""Ableton Live project discovery and dependency checks for sets and presets.

An .als set, and an .adg/.adv/.alc/.agr rack or preset, is gzipped XML. Every sample/device file the set needs appears as
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

Presets matter as much as sets: a rack in the User Library can load samples
and Max for Live devices from Factory Packs, so a Pack only counts as unused
when no set *and* no preset uses it. (.amxd devices are compiled Max patches,
not XML; what loads them is the rack or set that references them.)
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
_BUILTIN_MARKERS = ("/Core Library/", "/App-Resources/")
SET_EXT = ".als"

# For saying where in a set a file is used ("Track “Vox” › Drum Rack pad “Kick” › Simpler").
_TRACK_TAGS = {"AudioTrack": "Track", "MidiTrack": "Track", "GroupTrack": "Group track",
               "ReturnTrack": "Return track", "MasterTrack": "Main track", "MainTrack": "Main track"}
_PLACE_NAMES = {
    "OriginalSimpler": "Simpler", "MultiSampler": "Sampler", "DrumCell": "Drum Sampler",
    "DrumGroupDevice": "Drum Rack", "InstrumentGroupDevice": "Instrument Rack",
    "AudioEffectGroupDevice": "Audio Effect Rack", "MidiEffectGroupDevice": "MIDI Effect Rack",
    "InstrumentVector": "Wavetable", "Hybrid": "Hybrid Reverb", "Looper": "Looper",
    "MxDeviceAudioEffect": "Max for Live device", "MxDeviceInstrument": "Max for Live device",
    "MxDeviceMidiEffect": "Max for Live device", "PluginDevice": "plug-in", "AuPluginDevice": "plug-in",
    "FreezeSequencer": "frozen-track audio", "TakeLanes": "take lane", "GroovePool": "groove pool",
}
_BRANCH_NAMES = {"DrumBranch": "pad", "InstrumentBranch": "chain", "AudioEffectBranch": "chain",
                 "MidiEffectBranch": "chain"}
PRESET_EXTS = (".adg", ".adv", ".alc", ".agr")

# Shown wherever Mac Cleaner asks you to collect a project's files.
COLLECT_ALL_STEPS = ("In Live, open the set, then File → Collect All and Save. In the dialog, tick every source: "
                     "Elsewhere, Other Projects, User Library and Factory Packs, then Save.")


def parse_set(path: str) -> dict:
    """Return {'version': str, 'refs': [{'path','rel','pack','pack_id'}]} for a set or preset."""
    refs = []
    version = ""
    stack = []
    labels = []  # names of the tracks, chains and clips we're inside, parallel to stack
    cur = None

    def where() -> str:
        bits = []
        for tag, label in zip(stack, labels):
            if tag in _TRACK_TAGS:
                bits.append(f"{_TRACK_TAGS[tag]} “{label}”" if label else _TRACK_TAGS[tag])
            elif tag in _BRANCH_NAMES:
                bits.append(f"{_BRANCH_NAMES[tag]} “{label}”" if label else _BRANCH_NAMES[tag])
            elif tag == "AudioClip":
                bits.append(f"clip “{label}”" if label else "audio clip")
            elif tag in _PLACE_NAMES and (not bits or bits[-1] != _PLACE_NAMES[tag]):
                bits.append(_PLACE_NAMES[tag])
        return " › ".join(bits)

    def start(tag, attrs):
        nonlocal cur, version
        if not stack and tag == "Ableton":
            version = attrs.get("Creator", "")
        stack.append(tag)
        labels.append("")
        value = attrs.get("Value")
        if value and tag == "EffectiveName" and len(stack) > 2 and stack[-2] == "Name" \
                and (stack[-3] in _TRACK_TAGS or stack[-3] in _BRANCH_NAMES):
            labels[-3] = value
        elif value and tag == "Name" and len(stack) > 1 and stack[-2] == "AudioClip":
            labels[-2] = value
        if tag == "FileRef" and cur is None and not _IGNORED_CONTEXTS.intersection(stack):
            cur = {"path": "", "rel": "", "rel_parts": [], "name": "", "pack": "", "pack_id": "",
                   "rel_type": "", "depth": len(stack), "where": where(), "xml": "/".join(stack[1:])}
            return
        if cur is None:
            return
        parent = stack[-2] if len(stack) > 1 else ""
        if tag == "Path" and parent == "FileRef" and value:
            cur["path"] = value
        elif tag == "RelativePath" and value:
            cur["rel"] = value
        elif tag == "RelativePathType" and value:
            cur["rel_type"] = value
        elif tag == "RelativePathElement":
            cur["rel_parts"].append(attrs.get("Dir", "") or "..")
        elif tag == "Name" and parent == "FileRef" and value:
            cur["name"] = value
        elif tag == "LivePackName" and value:
            cur["pack"] = value
        elif tag == "LivePackId" and value:
            cur["pack_id"] = value

    def end(tag):
        nonlocal cur
        if cur is not None and tag == "FileRef" and len(stack) == cur["depth"]:
            rel = cur["rel"]
            if not rel and (cur["rel_parts"] or cur["name"]):
                rel = "/".join(cur["rel_parts"] + ([cur["name"]] if cur["name"] else []))
            if rel or cur["path"]:
                refs.append({"path": cur["path"], "rel": rel, "pack": cur["pack"], "pack_id": cur["pack_id"],
                             "rel_type": cur["rel_type"], "where": cur["where"], "xml": cur["xml"]})
            cur = None
        stack.pop()
        labels.pop()

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
        labels.clear()
        cur = None
        with open(path, "rb") as f:
            parser.ParseFile(f)
    return {"version": version, "refs": refs}


def is_preset(path: str) -> bool:
    return path.lower().endswith(PRESET_EXTS)


def keep_advice(user: str) -> str:
    """What to do about a file that `user` (a set or preset) still loads."""
    name = os.path.basename(user)
    if is_preset(user):
        return (f"The preset {name} loads it. Keep it here, or add the file to your User Library from Live's "
                "browser and re-save the preset; then it can be moved.")
    return f"{name} uses it. {COLLECT_ALL_STEPS} After that it can be moved."


def _inside(path: str, folder: str) -> bool:
    return os.path.normpath(path).startswith(os.path.normpath(folder) + os.sep)


def _pack_for(ref: dict, found: str | None, packs: list) -> str | None:
    """Which Pack a reference comes from: the installed Pack folder it resolved
    into, else the Pack Live recorded for it, else '…/Factory Packs/<name>/' in
    its path. None for the built-in Core Library and for non-Pack files."""
    shown = found or ref["path"] or ref["rel"]
    if any(m in shown for m in _BUILTIN_MARKERS):
        return None
    if found:
        n = os.path.normpath(found)
        for p in packs:
            if n.startswith(os.path.normpath(p["path"]) + os.sep):
                return p["name"]
    if ref.get("pack_id"):
        for p in packs:
            if p.get("id") and p["id"] == ref["pack_id"]:
                return p["name"]
    if ref.get("pack"):
        return ref["pack"]
    if "/Factory Packs/" in shown:
        return shown.split("/Factory Packs/", 1)[1].split("/", 1)[0] or None
    return None


def check_set(path: str, project_dir: str | None, packs: list | None = None) -> dict:
    """Resolve every file a set or preset needs. `packs` = installed Packs (live_prefs)."""
    packs = packs or []
    parsed = parse_set(path)
    base = project_dir or os.path.dirname(path)
    counts = {"in_project": 0, "packs": 0, "external": 0, "missing": 0}
    examples = {"external": [], "missing": [], "missing_detail": []}
    external = []
    used = []  # every file that resolved, wherever it is
    pack_refs = {}  # pack name -> resolved?
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
        pack = _pack_for(ref, found, packs)
        if pack:
            pack_refs[pack] = pack_refs.get(pack, False) or bool(found)
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
                examples["missing_detail"].append({k: ref[k] for k in ("path", "rel", "rel_type", "pack", "where", "xml")})
    return {"version": parsed["version"], "refs": len(seen), **counts, "examples": examples,
            "external_paths": external, "used_paths": used, "pack_refs": pack_refs}


def _project_for(path: str, projects: set) -> str | None:
    d = os.path.dirname(path)
    while d and d != os.path.dirname(d):
        if d in projects:
            return d
        d = os.path.dirname(d)
    return None


def _is_backup(path: str) -> bool:
    return os.sep + "Backup" + os.sep in path


def _inside_pack(path: str, packs: list) -> bool:
    if any(m in path for m in _BUILTIN_MARKERS):
        return True
    n = os.path.normpath(path)
    return any(n.startswith(os.path.normpath(p["path"]) + os.sep) for p in packs)


def analyse_sets(con, cfg, cancel=None, state=None) -> None:
    """Parse every current set and every preset outside the Packs; store what
    each one needs. Presets *inside* a Pack only point at that Pack's own
    files, so they say nothing about whether you use it."""
    from . import live_prefs
    packs = live_prefs.installed_packs()
    projects = {r["path"] for r in con.execute("SELECT path FROM dirs WHERE kind='ableton-project'")}
    set_rows, preset_rows, ref_rows, pack_rows = [], [], [], []
    exts = (SET_EXT,) + PRESET_EXTS
    query = "SELECT path, ext, dataless FROM files WHERE ext IN (%s)" % ",".join("?" * len(exts))
    for r in con.execute(query, exts).fetchall():
        if cancel is not None and cancel.is_set():
            break
        path = r["path"]
        if _is_backup(path) or os.path.basename(path).startswith("._"):
            continue
        is_preset = r["ext"] != SET_EXT
        if is_preset and _inside_pack(path, packs):
            continue
        rows = preset_rows if is_preset else set_rows
        project = _project_for(path, projects)
        if r["dataless"]:
            rows.append((path, project, "", 0, 0, 0, 0, 0, "{}", "Only in iCloud (not downloaded)"))
            continue
        try:
            res = check_set(path, project, packs)
            rows.append((path, project, res["version"], res["refs"], res["in_project"], res["packs"],
                         res["external"], res["missing"], json.dumps(res["examples"]), None))
            ref_rows.extend((path, os.path.normpath(e)) for e in res["used_paths"])
            pack_rows.extend((path, name, int(found)) for name, found in res["pack_refs"].items())
        except Exception as e:  # corrupt/unreadable files shouldn't stop the scan
            rows.append((path, project, "", 0, 0, 0, 0, 0, "{}", f"Couldn't read: {e}"))
        if state is not None:
            state["current"] = path
    con.executemany("INSERT OR REPLACE INTO ableton_sets VALUES (?,?,?,?,?,?,?,?,?,?)", set_rows)
    con.executemany("INSERT OR REPLACE INTO ableton_presets VALUES (?,?,?,?,?,?,?,?,?,?)", preset_rows)
    con.executemany("INSERT INTO ableton_refs VALUES (?,?)", ref_rows)
    con.executemany("INSERT INTO ableton_pack_refs VALUES (?,?,?)", pack_rows)
    con.commit()


def packs_overview(con, cfg) -> dict:
    """Every installed Factory Pack: size, and which sets and presets use it.
    'Unused' only when nothing uses it AND every set and preset could be read."""
    from . import db, live_prefs, safety
    info = live_prefs.read_library()
    installed = live_prefs.installed_packs(info)
    presets = {r["path"] for r in con.execute("SELECT path FROM ableton_presets")}
    users = defaultdict(lambda: {"sets": set(), "presets": set(), "missing": False, "name": ""})
    for r in con.execute("SELECT user_path, pack, found FROM ableton_pack_refs"):
        u = users[r["pack"].casefold()]
        u["name"] = u["name"] or r["pack"]
        u["presets" if r["user_path"] in presets else "sets"].add(r["user_path"])
        if not r["found"]:
            u["missing"] = True
    unchecked = safety.unchecked_sets(con)
    out, matched = [], set()
    for p in installed:
        keys = {p["name"].casefold(), os.path.basename(p["path"]).casefold()}
        matched |= keys
        sets, pres = set(), set()
        for k in keys:
            sets |= users[k]["sets"] if k in users else set()
            pres |= users[k]["presets"] if k in users else set()
        row = con.execute("SELECT alloc, size FROM dirs WHERE path=?", (p["path"],)).fetchone()
        if not p["exists"]:
            status = "missing-used" if (sets or pres) else "missing"
        elif sets or pres:
            status = "used"
        elif unchecked:
            status = "unknown"
        else:
            status = "unused"
        out.append({"name": p["name"], "path": p["path"], "listed": p["listed"], "exists": p["exists"],
                    "alloc": row["alloc"] if row else None, "status": status,
                    "sets": sorted(sets), "presets": sorted(pres)})
    # Packs your sets or presets use that aren't installed at all.
    for key, u in users.items():
        if key in matched:
            continue
        out.append({"name": u["name"], "path": None, "listed": False, "exists": False, "alloc": None,
                    "status": "missing-used", "sets": sorted(u["sets"]), "presets": sorted(u["presets"])})
    order = {"missing-used": 0, "unknown": 1, "used": 2, "unused": 3, "missing": 4}
    out.sort(key=lambda x: (order[x["status"]], -(x["alloc"] or 0)))
    meta = db.meta(con)
    return {
        "packs": out, "cfg_found": info is not None, "cfg_path": (info or {}).get("cfg_path"),
        "unchecked": len(unchecked), "unchecked_examples": [u["path"] for u in unchecked[:5]],
        "presets_checked": len(presets), "rescan_needed": int(meta.get("index_version", 0) or 0) < 2,
        "collect_steps": COLLECT_ALL_STEPS,
    }


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
    sub = defaultdict(lambda: {"backup": 0, "asd": 0, "nbackups": 0, "newest": 0.0, "newest_set": None})
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
        elif r["mtime"] >= sub[proj]["newest"]:
            sub[proj]["newest"] = r["mtime"]
            sub[proj]["newest_set"] = r["path"]

    # Live's own "recently opened" list, mapped to projects (0 = most recent).
    from . import live_prefs, marks
    opened = {}
    for rank, set_path in enumerate(live_prefs.recent_sets()):
        proj = _project_for(set_path, project_paths)
        if proj and proj not in opened:
            opened[proj] = rank
    important = marks.important_lookup()

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
            "newest_set": extra.get("newest_set") or (sets[0]["path"] if sets else None),
            "opened_rank": opened.get(p), "important": marks.is_important(p, important),
            "external_total": sum(s["external"] for s in sets), "missing_total": sum(s["missing"] for s in sets),
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
        "recent_from_live": bool(opened), "collect_steps": COLLECT_ALL_STEPS,
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


def recheck_project(con, project: str) -> dict:
    """Re-read one project's sets and presets from disk right now (after you
    Collect All and Save), without a full rescan."""
    from . import live_prefs
    if not os.path.isdir(project):
        raise FileNotFoundError(f"{project} isn't there any more")
    packs = live_prefs.installed_packs()
    old = [r["path"] for r in con.execute("SELECT path FROM ableton_sets WHERE project=? "
                                          "UNION ALL SELECT path FROM ableton_presets WHERE project=?",
                                          (project, project))]
    for p in old:
        con.execute("DELETE FROM ableton_refs WHERE set_path=?", (p,))
        con.execute("DELETE FROM ableton_pack_refs WHERE user_path=?", (p,))
    con.execute("DELETE FROM ableton_sets WHERE project=?", (project,))
    con.execute("DELETE FROM ableton_presets WHERE project=?", (project,))
    results = []
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [d for d in dirnames if d != "Backup" and not d.startswith(".")]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if fn.startswith("._") or ext not in (SET_EXT,) + PRESET_EXTS:
                continue
            path = os.path.join(dirpath, fn)
            table = "ableton_sets" if ext == SET_EXT else "ableton_presets"
            try:
                res = check_set(path, project, packs)
            except Exception as e:
                con.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (path, project, "", 0, 0, 0, 0, 0, "{}", f"Couldn't read: {e}"))
                results.append({"path": path, "error": str(e)})
                continue
            con.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (path, project, res["version"], res["refs"], res["in_project"], res["packs"],
                         res["external"], res["missing"], json.dumps(res["examples"]), None))
            con.executemany("INSERT INTO ableton_refs VALUES (?,?)",
                            [(path, os.path.normpath(e)) for e in res["used_paths"]])
            con.executemany("INSERT INTO ableton_pack_refs VALUES (?,?,?)",
                            [(path, n, int(f)) for n, f in res["pack_refs"].items()])
            if ext == SET_EXT:
                results.append({"path": path, "external": res["external"], "missing": res["missing"]})
    con.commit()
    sets = [r for r in results if "error" not in r]
    status = "no-sets" if not results else "missing" if any(r["missing"] for r in sets) else \
        "external" if any(r["external"] for r in sets) else "unknown" if len(sets) < len(results) else "ok"
    return {"project": project, "status": status, "sets": results}


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
