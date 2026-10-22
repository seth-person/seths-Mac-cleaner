"""Proposals: for any folder, where each thing in it would go, and why.

Read-only. Every item at the top of the folder gets one proposal:

  action/dest  move to a folder, trash, or keep where it is
  rule, reason what decided it, in words
  confidence   "sure" (a Stem Prep record, or already in the right project),
               "likely" (a name or track-name match), "guess" (a rule by type)
  blockers     why it can't move yet (protected, used by a set elsewhere,
               needs Collect All); a blocked item is never ticked
  warnings     things to know (pinned in Live's browser, only in iCloud)

Sure and likely moves start ticked; guesses never do. Your own changes to a
folder's proposals are saved, so a long list can be reviewed over several days.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

from . import ableton, config, exports, inbox, listen, live_prefs, marks, safety

STATUS_WORDS = [
    ("finished", ("complete", "completed", "finished", "released", "release", "releases", "done", "master", "masters")),
    ("dormant", ("dormant", "paused", "on hold", "later")),
    ("archive", ("archive", "archived", "old", "abandoned", "practice", "graveyard")),
    ("active", ("active", "in progress", "current", "wip", "working")),
]


def _lib(cfg: dict) -> dict:
    return config.library_paths(cfg)


def _status_folder(cfg: dict, wanted: str) -> tuple:
    """(status name, path) for a status like "finished", matching your own names."""
    lib = _lib(cfg)
    statuses = list(lib["statuses"])
    for s in statuses:
        if s.casefold() == wanted or s.casefold().startswith(wanted[:4]):
            return s, lib["statuses"][s]
    order = {"active": 0, "dormant": 1, "finished": 2, "archive": 3}
    i = min(order.get(wanted, 0), len(statuses) - 1)
    return statuses[i], lib["statuses"][statuses[i]]


def guess_status(path: str, mtime: float) -> tuple:
    """(status, why, from_folder_name): from the folders a project sits in
    ("Completed Projects" -> finished), else from when it was last saved."""
    home = str(config.home())
    parts = os.path.dirname(path)[len(home):].split(os.sep)
    for part in reversed(parts):
        low = part.casefold()
        for status, words in STATUS_WORDS:
            for w in words:
                if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])" + (r"(?! storage)" if w == "active" else ""), low):
                    return status, f"it's in a folder called “{part}”", True
    age = (time.time() - (mtime or 0)) / 86400
    if age < 45:
        return "active", "it was saved in the last 45 days", False
    if age < 365:
        return "dormant", "it was last saved over 45 days ago", False
    return "archive", "it was last saved over a year ago", False


def folder_problem(folder: str, cfg: dict) -> str | None:
    """Why a folder can't be planned (its contents are managed elsewhere), or None."""
    if not os.path.isdir(folder):
        return "That folder doesn't exist"
    real = os.path.realpath(folder)
    h = os.path.realpath(config.home())
    if not (real + os.sep).startswith(h + os.sep):
        return "Only folders inside your home folder can be organised"
    lib_dir = os.path.join(h, "Library")
    cloud = os.path.realpath(config.expand(cfg["cloud_root"], cfg))
    if (real + os.sep).startswith(lib_dir + os.sep) and not (real + os.sep).startswith(cloud + os.sep):
        return "That's inside Library, where macOS and apps keep their data"
    if os.path.splitext(real)[1].lower() in (".photoslibrary", ".musiclibrary", ".fcpbundle", ".app", ".logicx"):
        return "That's a library an app manages; it's kept as one item"
    if safety._in_project(real) and not real.endswith(".als"):
        return "That's inside an Ableton project. Organise the folder the project is in instead"
    if any(part.casefold() == "rekordbox" for part in real.split(os.sep)):
        return "That's rekordbox's folder; moving its tracks breaks rekordbox"
    info = live_prefs.read_library()
    if info and info.get("user_library"):
        ul = safety.norm(os.path.realpath(info["user_library"]))
        if safety.norm(real) == ul or safety.norm(real).startswith(ul + "/"):
            return "That's Live's User Library; only Live should move things in it"
    music_ableton = os.path.join(h, "Music", "Ableton")
    if (real + os.sep).startswith(music_ableton + os.sep) or real == music_ableton:
        return "That's Live's own library folder"
    return None


def _project_status(con) -> dict:
    """Per project: the newest set's outside and missing files (that's what decides
    whether it may move), and whether older sets in the folder have problems."""
    out = {}
    if con is None:
        return out
    rows = con.execute("SELECT s.project, s.external, s.missing, s.error, s.examples, f.mtime FROM ableton_sets s "
                       "LEFT JOIN files f ON f.path = s.path WHERE s.project IS NOT NULL").fetchall()
    by = {}
    for r in rows:
        by.setdefault(r["project"], []).append(r)
    for proj, sets in by.items():
        new = max(sets, key=lambda r: r["mtime"] or 0)
        older = [r for r in sets if r is not new]
        stable = ableton.stable_outside({"external": new["external"], "examples": json.loads(new["examples"] or "{}")})
        out[proj] = {"external": max(0, (new["external"] or 0) - stable), "missing": new["missing"] or 0,
                     "library_files": stable, "sets": len(sets),
                     "errors": 1 if new["error"] else 0,
                     "older_problems": sum(1 for r in older if r["external"] or r["missing"] or r["error"])}
    return out


def _under(path: str, folder: str) -> bool:
    n, f = safety.norm(path), safety.norm(folder)
    return n == f or n.startswith(f + "/")


def _proposal(item: dict, **kw) -> dict:
    p = {k: item[k] for k in ("path", "name", "kind", "category", "size", "mtime", "age_days", "is_dir")}
    p.update(action="keep", dest=None, rule="", reason="", confidence=None, blockers=[], warnings=[])
    p.update(kw)
    return p


def propose(item: dict, ctx: dict) -> dict:
    cfg, lib, idx = ctx["cfg"], ctx["lib"], ctx["idx"]
    exports_dir = ctx["exports_dir"]
    path = item["path"]

    reason = safety.protected_reason(path, cfg)
    if reason:
        return _proposal(item, rule="Protected", reason=f"{item['name']} {reason}", blockers=[reason])
    users = ctx["used"].users(path) if ctx["used"] else []
    if users:
        apps = [u for u in users if not u.startswith("/")]
        return _proposal(item, rule="Used by " + (apps[0].split(" “")[0].replace("the ", "") if apps else "Ableton"),
                         reason=ableton.keep_advice(apps[0] if apps else users[0]),
                         blockers=["used by " + safety.describe_users(users)])

    if item["kind"] == "ableton-project":
        if path in ctx["archivable"]:
            if _under(path, lib["broken"]):
                return _proposal(item, rule="Broken", reason="already in the broken projects folder", confidence="sure")
            return _proposal(item, action="move", dest=lib["broken"], rule="Broken → archive", confidence="sure",
                             reason="you marked it “Archive as broken”")
        status, why, from_name = guess_status(path, item["mtime"])
        name, dest = _status_folder(cfg, status)
        if _under(path, lib["projects"]):
            here = os.path.relpath(os.path.dirname(path), lib["projects"]).split(os.sep)[0]
            if here in lib["statuses"]:
                return _proposal(item, rule="Projects", reason=f"already in Projects/{here}", confidence="sure")
        st = ctx["projects"].get(path, {})
        blockers = []
        if st.get("errors"):
            blockers.append("its newest set couldn't be read: open it in Live, or rescan")
        if st.get("missing"):
            blockers.append(f"its newest set has {st['missing']} missing file{'s' if st['missing'] > 1 else ''}: find them in Live first")
        if st.get("external"):
            blockers.append(f"its newest set uses {st['external']} file{'s' if st['external'] > 1 else ''} outside its folder: "
                            "Collect All and Save in Live first")
        warnings = []
        if not st:
            warnings.append("not checked by the last scan: rescan before moving it")
        elif st.get("older_problems") and not blockers:
            n = st["older_problems"]
            warnings.append(f"{n} older set{'s' if n != 1 else ''} in it aren't collected; "
                            "the newest one is self-contained, so it's safe to move")
        if blockers and path in ctx["move_anyway"]:
            warnings = [b + " (you allowed moving it anyway)" for b in blockers] + warnings
            blockers = []
        return _proposal(item, action="move", dest=dest, rule=f"Projects → {name}",
                         reason=f"{name}, because {why}", confidence="likely" if from_name else "guess",
                         blockers=blockers, warnings=warnings, project_status=st)

    if item["is_dir"]:
        g = idx.group_for_folder(path) if idx else None
        if g:
            warnings = ["some of these files are only in iCloud"] if g["dataless"] else []
            if g.get("copy_of"):
                return _copy_proposal(item, g, len(g["files"]))
            if g["project"]:
                received = g.get("received")
                dest = os.path.join(g["project"], exports.RECEIVED_DIR) if received else os.path.join(g["project"], exports_dir, "Stems")
                if _under(path, dest):
                    return _proposal(item, rule="Stems", reason="already in the project's stems folder",
                                     confidence="sure", project=g["project"])
                return _proposal(item, action="move", dest=dest, rule="Received stems → project" if received else "Stems → project",
                                 reason=f"{'received stems' if received else 'stems'} for {_project_name(g['project'])} "
                                        f"({len(g['files'])} files): {g['why']}",
                                 confidence=g["confidence"], warnings=warnings, project=g["project"])
            warnings.append(f"might be a stem export ({len(g['files'])} files exported together), "
                            "but it doesn't match any project")
            p = _rule_proposal(item, cfg)
            p["warnings"] = warnings + p["warnings"]
            return p

    if item["kind"] == "file" and item["category"] == "audio":
        g = ctx["groups_here"].get(path)
        if g:
            if g.get("copy_of"):
                return _copy_proposal(item, g, 1)
            if g["project"]:
                received = g.get("received")
                base = os.path.join(g["project"], exports.RECEIVED_DIR) if received else os.path.join(g["project"], exports_dir, "Stems")
                return _proposal(item, action="move", dest=os.path.join(base, g["prefix"]),
                                 rule="Received stems → project" if received else "Stems → project",
                                 reason=f"one of {len(g['files'])} {'received stems' if received else 'stems'} "
                                        f"for {_project_name(g['project'])}: {g['why']}",
                                 confidence=g["confidence"], project=g["project"])
            p = _rule_proposal(item, cfg)
            p["warnings"].append(f"one of {len(g['files'])} files exported together as “{g['prefix']}”, "
                                 "but they don't match any project")
            return p
        kind = exports.audio_kind(item["name"])
        if kind in ("master", "bounce") and idx:
            proj = idx.project_for_name(item["name"])
            if proj:
                sub = "Master" if kind == "master" else "Bounces"
                dest = os.path.join(proj, exports_dir, sub)
                what = f"{'a master' if kind == 'master' else 'a bounce'} of {_project_name(proj)} (the name matches)"
                newer = _newer_bounce(ctx["bounces"], item["name"], path) if kind == "bounce" else None
                if newer:
                    dest = os.path.join(dest, OLDER_BOUNCES)
                    what = (f"an older bounce of {_project_name(proj)} (v{listen.song_key(item['name'])[1]}; "
                            f"the newest is v{newer['version']})")
                if _under(path, dest):
                    return _proposal(item, rule=sub, reason="already filed in its project", confidence="sure")
                return _proposal(item, action="move", dest=dest, rule=f"{sub} → project",
                                 reason=what, confidence="likely", project=proj)

    return _rule_proposal(item, cfg)


OLDER_BOUNCES = "Older versions"


def _version(v: str | None) -> tuple:
    try:
        return tuple(int(x) for x in (v or "").split("."))
    except ValueError:
        return ()


def _newer_bounce(bounces: dict, name: str, path: str) -> dict | None:
    """The newest bounce of the same song with a higher version number, if any."""
    key, version = listen.song_key(name)
    mine = _version(version)
    if not mine:
        return None
    best = None
    for b in bounces.get(key, []):
        v = _version(b["version"])
        if b["path"] != path and exports.audio_kind(b["name"]) == "bounce" and v > mine \
                and (best is None or v > _version(best["version"])):
            best = b
    return best


def _copy_proposal(item: dict, g: dict, n: int) -> dict:
    """Stems that are already filed in a project: this copy can go (never ticked)."""
    what = "These stems are" if n > 1 else "This file is"
    same = exports.copy_checked(g)
    checked = " (checked: the files are identical)" if same else " (same names and sizes)"
    return _proposal(item, action="trash", rule="Copy of filed stems", confidence="likely" if same else "guess",
                     reason=f"{what} already in {_project_name(g['copy_project'])}/"
                            f"{os.path.relpath(g['copy_of'], g['copy_project'])}{checked}",
                     warnings=["check the filed copy plays before you trash this one"], project=g["project"])


def _rule_proposal(item: dict, cfg: dict) -> dict:
    path = item["path"]
    s = inbox.suggest(item, cfg)
    if not s:
        return _proposal(item, reason="No rule matched; choose where it goes, or leave it.")
    if s["action"] == "move" and s.get("dest") and _under(path, s["dest"]):
        return _proposal(item, rule=s["rule"], reason="already where its rule says", confidence="sure")
    return _proposal(item, action=s["action"], dest=s.get("dest"), rule=s["rule"], confidence="guess",
                     reason=f"Rule: {s['rule']}", risk=s.get("risk"))


def _project_name(p: str) -> str:
    n = os.path.basename(p)
    return n[: -len(" Project")] if n.endswith(" Project") else n


def plan_folder(con, cfg: dict, folder: str) -> dict:
    folder = os.path.abspath(os.path.expanduser(folder))
    problem = folder_problem(folder, cfg)
    if problem:
        return {"folder": folder, "error": problem, "items": []}
    idx = exports.index(con) if con is not None else None
    groups_here = {}
    if idx:
        for g in idx.groups:
            if safety.norm(g["folder"]) == safety.norm(folder):
                for f in g["files"]:
                    groups_here[f["path"]] = g
    ctx = {"cfg": cfg, "lib": _lib(cfg), "idx": idx, "used": safety.UsedIndex(con, cfg) if con is not None else None,
           "projects": _project_status(con), "groups_here": groups_here,
           "bounces": listen._bounce_index(con) if con is not None else {},
           "archivable": marks.flagged("archive_broken"), "move_anyway": marks.flagged("move_anyway"),
           "exports_dir": _lib(cfg)["exports"]}
    pins = [os.path.realpath(p) for p in live_prefs.pinned_folders()]
    active = any(safety.norm(str(config.expand(p, cfg))) == safety.norm(folder) for p in cfg.get("active_inboxes", []))
    stale = float(cfg.get("stale_days", 21))
    items = []
    try:
        entries = [e for e in os.scandir(folder) if not e.name.startswith(".") and e.name not in ("Icon\r", "$RECYCLE.BIN")]
    except OSError as e:
        return {"folder": folder, "error": str(e), "items": []}
    for e in entries:
        try:
            item = inbox.describe(e.path)
        except OSError:
            continue
        p = propose(item, ctx)
        real = os.path.realpath(e.path)
        hit = [q for q in pins if q == real or q.startswith(real + os.sep)]
        if hit and p["action"] == "move":
            p["warnings"].append("pinned in Live's browser: re-add it there after moving")
        recent = active and item["age_days"] < stale
        if recent and p["action"] != "keep":
            p["warnings"].append(f"you touched it in the last {int(stale)} days (this folder is your workspace)")
        p["ticked"] = p["action"] == "move" and p["confidence"] in ("sure", "likely") and not p["blockers"] and not recent
        items.append(p)
    items.sort(key=lambda p: (p["action"] == "keep", p["dest"] or "", -(p["size"] or 0)))
    saved = load_decisions(folder)
    return {"folder": folder, "items": items, "decisions": saved.get("decisions", {}),
            "saved_at": saved.get("saved_at"), "library": _lib(cfg),
            "has_tracks": bool(idx and idx.has_tracks)}


# --- saved decisions ---------------------------------------------------------
def _plans_path():
    return config.app_dir() / "plans.json"


def _load_all() -> dict:
    try:
        return json.loads(_plans_path().read_text())
    except (OSError, ValueError):
        return {}


def _key(folder: str) -> str:
    return hashlib.sha1(safety.norm(os.path.abspath(folder)).encode()).hexdigest()[:16]


def load_decisions(folder: str) -> dict:
    return _load_all().get(_key(folder), {})


def save_decisions(folder: str, decisions: dict) -> dict:
    if not isinstance(decisions, dict):
        raise ValueError("decisions must be an object")
    clean = {}
    for path, d in decisions.items():
        if not isinstance(d, dict) or d.get("action") not in ("move", "trash", "keep"):
            continue
        clean[str(path)] = {"action": d["action"], "dest": str(d.get("dest") or ""), "ticked": bool(d.get("ticked"))}
    data = _load_all()
    data[_key(folder)] = {"folder": os.path.abspath(folder), "saved_at": time.time(), "decisions": clean}
    tmp = _plans_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, _plans_path())
    return data[_key(folder)]


def preview(items: list, cfg: dict) -> list:
    """What a batch would do, item by item, without doing it (every check included)."""
    from . import actions
    return actions.apply([{"path": it.get("path"), "action": it.get("action"), "dest": it.get("dest")}
                          for it in items if it.get("action") in ("move", "trash")], cfg, dry_run=True)


def places(con, cfg: dict) -> list:
    """Folders offered in the Plan tab's picker."""
    out = []
    seen = set()

    def add(path, label):
        path = str(path)
        if path not in seen and os.path.isdir(path):
            seen.add(path)
            out.append({"path": path, "label": label})
    for p in config.inbox_paths(cfg):
        add(p, p.name)
    add(config.home() / "Documents", "Documents")
    add(config.expand("{cloud}", cfg), "iCloud Drive")
    lib = _lib(cfg)
    if lib["ready"]:
        add(lib["root"], "Library")
    top = "Library" if lib["ready"] else "iCloud Drive"
    try:
        for e in sorted(os.scandir(lib["root"]), key=lambda e: e.name.lower()):
            if e.is_dir() and not e.name.startswith(".") and not folder_problem(e.path, cfg):
                add(e.path, f"{top} › {e.name}")
    except OSError:
        pass
    return out
