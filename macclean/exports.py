"""What your exports are and which song they belong to. Read-only.

  kinds        an audio file is a "master" (MASTER, premaster, final), a
               "bounce" (has a version number, V10) or "other"
  stem groups  files Live exported together with "All Individual Tracks":
               3+ WAV/AIFF files in one folder, written within minutes of
               each other, the same length (so the same size), named
               "<name> <track>.wav", usually with "<name>.wav" as the full mix
  Stem Prep    the run records the Stem Prep extension writes in Live's
               Extensions Data folder; a stem group that matches one is "sure"
  matching     a stem group belongs to a project when it's inside it, when its
               name matches the project or one of its sets, when most of its
               file names are that project's track names, or when the project's
               sets use the files as samples
  received     stems that came from somewhere else (sent to you for a remix, say,
               or exported from another project) rather than exported from it: the project's sets use them as samples, its tracks are
               named after the files (what Live does when you drag them in), or
               they're older than the project's first set
  copies       a stem group whose every file (same name, same size) is also in
               a folder inside a project is a copy of stems already filed there
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from collections import Counter, defaultdict

from . import config, db, safety

STEM_EXTS = (".wav", ".aif", ".aiff")
GROUP_GAP_S = 600           # files further apart than this are separate exports
MIN_STEMS = 3
MIN_STEM_BYTES = 3_000_000  # a stem covers a whole section: loops and one-shots are smaller
TRACK_MATCH = 0.6           # share of a group's track names that must match a project
RECORD_WINDOW_S = 6 * 3600  # how long after a Stem Prep run its files may appear
RECEIVED_DIR = os.path.join("Samples", "Received Stems")
BEFORE_PROJECT_S = 86400    # stems this much older than a project's first set came from somewhere else
INGREDIENT_DIRS = {"samples", "imported", "processed", "recorded", "freeze", "consolidate",
                   "reverse", "crop", "backup"}

_MASTER = re.compile(r"(?<![a-z])(master(ed)?|pre-?master|final)(?![a-z])", re.I)
_VERSION = re.compile(r"(?<![a-z0-9])v\s?\d+(?:\.\d+)?(?![a-z0-9])", re.I)
_SEP = " _-"


def norm_name(s: str) -> str:
    return " ".join(unicodedata.normalize("NFC", s).casefold().split())


def audio_kind(name: str) -> str:
    stem = os.path.splitext(os.path.basename(name))[0]
    if _MASTER.search(stem):
        return "master"
    if _VERSION.search(stem):
        return "bounce"
    return "other"


# --- stem groups -------------------------------------------------------------
def _prefix(stems: list) -> tuple:
    """(prefix, full-mix stem or None) for names exported together."""
    by_len = sorted(stems, key=len)
    for cand in by_len[:3]:
        if all(s == cand or (s.startswith(cand) and s[len(cand)] in _SEP) for s in stems):
            return cand, cand
    cp = os.path.commonprefix(stems)
    if not all(len(s) > len(cp) for s in stems):
        return "", None
    cut = max(cp.rfind(c) for c in _SEP)
    if cut < 0 or not cp[:cut].strip(_SEP):
        return "", None
    if all(len(s) > len(cp) and s[len(cp)] in _SEP for s in stems):
        cut = len(cp)
    return cp[:cut].rstrip(_SEP), None


def _group(parent: str, files: list) -> dict | None:
    """files: rows in one cluster -> a stem group, or None."""
    if len(files) < MIN_STEMS:
        return None
    size, n = Counter(f["size"] for f in files).most_common(1)[0]
    if n < MIN_STEMS:
        return None
    files = [f for f in files if abs(f["size"] - size) <= max(4096, size * 0.005)]
    if len(files) < MIN_STEMS or size < MIN_STEM_BYTES:
        return None
    stems = [os.path.splitext(f["name"])[0] for f in files]
    prefix, mix = _prefix(stems)
    if len(prefix.strip(_SEP)) < 2:
        return None
    out_files, tracks = [], []
    for f, st in zip(files, stems):
        track = st[len(prefix):].strip(_SEP) if st != mix else ""
        out_files.append({"path": f["path"], "name": f["name"], "track": track, "size": f["size"]})
        if track:
            tracks.append(track)
    if len(tracks) < MIN_STEMS - 1:
        return None
    mt = [f["mtime"] for f in files]
    return {"folder": parent, "prefix": prefix, "files": sorted(out_files, key=lambda x: x["name"].lower()),
            "tracks": sorted(set(tracks), key=str.lower), "mix": next((f["path"] for f, st in zip(files, stems)
                                                                     if st == mix), None),
            "first": min(mt), "last": max(mt), "bytes": sum(f["size"] for f in files),
            "dataless": any(f["dataless"] for f in files)}


def _ingredient_folder(parent: str, projects: list) -> bool:
    proj = _project_of(parent, projects)
    if not proj:
        return False
    rel = os.path.relpath(parent, proj).split(os.sep)
    return any(part.casefold() in INGREDIENT_DIRS for part in rel)


def _project_of(path: str, projects: list) -> str | None:
    n = safety.norm(path)
    best = None
    for p in projects:
        pn = safety.norm(p)
        if (n == pn or n.startswith(pn + "/")) and (best is None or len(p) > len(best)):
            best = p
    return best


def find_stem_groups(con) -> list:
    projects = [r["path"] for r in con.execute("SELECT path FROM dirs WHERE " + db.PROJECTS)]
    by_parent = defaultdict(list)
    q = "SELECT path, parent, name, size, mtime, dataless FROM files WHERE ext IN (%s)" % ",".join("?" * len(STEM_EXTS))
    for r in con.execute(q, STEM_EXTS):
        by_parent[r["parent"]].append(dict(r))
    groups = []
    for parent, files in by_parent.items():
        if len(files) < MIN_STEMS or safety.in_sound_library(parent) or _ingredient_folder(parent, projects):
            continue
        files.sort(key=lambda f: f["mtime"] or 0)
        cluster = [files[0]]
        for f in files[1:]:
            if (f["mtime"] or 0) - (cluster[-1]["mtime"] or 0) > GROUP_GAP_S:
                g = _group(parent, cluster)
                if g:
                    groups.append(g)
                cluster = []
            cluster.append(f)
        g = _group(parent, cluster)
        if g:
            groups.append(g)
    for g in groups:
        g["in_project"] = _project_of(g["folder"], projects)
    return groups


# --- Stem Prep run records ---------------------------------------------------
def stem_prep_dirs() -> list:
    root = config.home() / "Library" / "Application Support" / "Ableton" / "Extensions Data"
    try:
        return [str(d / "stem-runs") for d in root.iterdir() if (d / "stem-runs").is_dir()]
    except OSError:
        return []


def stem_prep_runs() -> list:
    runs = []
    for d in stem_prep_dirs():
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            if not n.endswith(".json"):
                continue
            p = os.path.join(d, n)
            try:
                rec = json.loads(open(p, encoding="utf-8").read())
            except (OSError, ValueError):
                continue
            if not isinstance(rec, dict) or rec.get("format") != 1 or not isinstance(rec.get("tracks"), list):
                continue
            ts = _parse_iso(rec.get("created_at", ""))
            if ts is None:
                continue
            runs.append({"file": p, "song": str(rec.get("song") or ""), "created": ts,
                         "tracks": [t.get("name", "") for t in rec["tracks"] if isinstance(t, dict) and t.get("name")],
                         "range": rec.get("range") or {}, "switched_off": rec.get("main_effects_switched_off") or []})
    return runs


def _parse_iso(s: str) -> float | None:
    """'2026-10-21T12:17:56-07:00' -> timestamp (Python 3.9 can't parse every offset form)."""
    m = re.match(r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.\d+)?(Z|[+-]\d\d:?\d\d)?$", s or "")
    if not m:
        return None
    import calendar
    y, mo, d, hh, mi, ss, tz = m.groups()
    t = calendar.timegm((int(y), int(mo), int(d), int(hh), int(mi), int(ss), 0, 0, 0))
    if tz and tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        tz = tz[1:].replace(":", "")
        t -= sign * (int(tz[:2]) * 3600 + int(tz[2:]) * 60)
    elif not tz:
        t = time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
    return float(t)


def _file_stems(g: dict) -> list:
    return [os.path.splitext(f["name"])[0] for f in g["files"]]


def _overlap(a: list, b: set) -> float:
    a = {norm_name(x) for x in a if x}
    return len(a & b) / len(a) if a else 0.0


# --- matching to projects ----------------------------------------------------
class Index:
    """Projects, their song names and track names, and every stem group matched to them.
    Built once per scan (plus Stem Prep records, which are re-read each time)."""

    def __init__(self, con):
        from . import listen
        self.projects = [r["path"] for r in con.execute("SELECT path FROM dirs WHERE " + db.PROJECTS)]
        self.by_key = defaultdict(set)
        self.tracks = defaultdict(set)
        sets_of = defaultdict(list)
        for r in con.execute("SELECT path, project FROM ableton_sets WHERE project IS NOT NULL"):
            sets_of[r["project"]].append(r["path"])
        for p in self.projects:
            name = os.path.basename(p)
            if name.endswith(" Project"):
                name = name[: -len(" Project")]
            self.by_key[listen.song_key(name)[0]].add(p)
            for s in sets_of.get(p, []):
                self.by_key[listen.song_key(s)[0]].add(p)
        set_project = {s: p for p, ss in sets_of.items() for s in ss}
        try:
            rows = con.execute("SELECT set_path, name FROM ableton_tracks").fetchall()
        except Exception:  # an old scan without track names
            rows = []
        self.has_tracks = bool(rows)
        self.by_track = defaultdict(set)
        for r in rows:
            p = set_project.get(r["set_path"])
            if p:
                t = norm_name(r["name"])
                self.tracks[p].add(t)
                self.by_track[t].add(p)
        self.ref_names = defaultdict(set)  # file name -> projects whose sets use a file of that name
        self.ref_paths = set()
        for r in con.execute("SELECT set_path, ref_path FROM ableton_refs"):
            self.ref_paths.add(safety.norm(r["ref_path"]))
            p = set_project.get(r["set_path"])
            if p:
                self.ref_names[norm_name(os.path.basename(r["ref_path"]))].add(p)
        self.first_save = {}  # project -> its oldest set's last save
        for r in con.execute("SELECT s.project, MIN(MIN(COALESCE(NULLIF(f.birth, 0), f.mtime), f.mtime)) AS t "
                             "FROM ableton_sets s JOIN files f ON f.path = s.path "
                             "WHERE s.project IS NOT NULL GROUP BY s.project"):
            if r["t"]:
                self.first_save[r["project"]] = r["t"]
        self.groups = find_stem_groups(con)
        self.runs = stem_prep_runs()
        for g in self.groups:
            self._match(g)
            self._received(g)
        for g in self.groups:
            self._find_copy(con, g)

    def project_for_name(self, name: str) -> str | None:
        from . import listen
        hits = self.by_key.get(listen.song_key(name)[0]) or set()
        return sorted(hits)[0] if len(hits) == 1 else None

    def _match(self, g: dict) -> None:
        g["project"], g["confidence"], g["why"], g["stem_prep"] = None, None, "", None
        for run in self.runs:
            if run["created"] - 60 <= g["first"] <= run["created"] + RECORD_WINDOW_S \
                    and _overlap(g["tracks"], {norm_name(t) for t in run["tracks"]}) >= TRACK_MATCH:
                g["stem_prep"] = {"file": run["file"], "song": run["song"], "created": run["created"]}
                break
        if g["in_project"]:
            g["project"], g["confidence"], g["why"] = g["in_project"], "sure", "already inside the project"
            return
        by_name = self.project_for_name(g["prefix"])
        if not by_name and g["stem_prep"]:
            by_name = self.project_for_name(g["stem_prep"]["song"])
        best, score = None, 0.0
        if self.has_tracks:
            cands = Counter()
            names = {norm_name(t) for t in g["tracks"]}
            for t in names:
                for p in self.by_track.get(t, ()):
                    cands[p] += 1
            top = cands.most_common(2)
            if top and (len(top) == 1 or top[0][1] > top[1][1]):  # a tie on names like "Bass" means nothing
                best, score = top[0][0], top[0][1] / len(names)
        if by_name:  # track names are often generic; the export's name is the set's
            sure = bool(g["stem_prep"]) or best == by_name
            g["project"], g["confidence"] = by_name, "sure" if sure else "likely"
            g["why"] = "name matches the project" + (" and its track names" if best == by_name else "")
        elif best and score >= TRACK_MATCH:
            g["project"], g["confidence"] = best, "sure" if g["stem_prep"] else "likely"
            g["why"] = f"{round(score * 100)}% of the file names are this project's track names"
        if g["stem_prep"] and g["project"]:
            g["why"] += "; exported with Stem Prep"

    def _received(self, g: dict) -> None:
        """Mark stems you were sent rather than exported (see the top of this file)."""
        g["received"] = False
        names = [norm_name(f["name"]) for f in g["files"]]
        used = Counter(p for n in names for p in self.ref_names.get(n, ()))
        by_path = any(safety.norm(f["path"]) in self.ref_paths for f in g["files"])
        user, hits = used.most_common(1)[0] if used else (None, 0)
        if hits * 2 < len(names):
            user = None
        if not g["project"] and user:
            g["project"], g["confidence"] = user, "sure" if by_path else "likely"
            g["why"] = "this project's sets use them as samples"
        p = g["project"]
        if not p or g["stem_prep"]:
            return
        tracks = self.tracks.get(p, set())
        if _overlap(g["tracks"], tracks) >= TRACK_MATCH:  # the project's track names: an export
            return
        named_like_files = _overlap(_file_stems(g), tracks) >= TRACK_MATCH
        started = self.started(p)
        if user == p or named_like_files:
            why = "this project's sets use them as samples" if user == p else "the project's tracks are named after these files"
        elif started and g["first"] < started - BEFORE_PROJECT_S:
            days = int((started - g["first"]) // 86400)
            why = f"made {days} day{'s' if days != 1 else ''} before the project was started"
        else:
            return
        g["received"] = True
        g["why"] = (g["why"] if why in g["why"] else (g["why"] + "; " if g["why"] else "") + why) + \
            ", so they came from somewhere else (sent to you, or from another project)"

    def started(self, project: str) -> float | None:
        """When the project was started. Live rewrites a set's file on every save,
        so a set's own dates are its last save; the project folder is made once.
        Copying a folder can reset its date, so the oldest set counts too."""
        times = [self.first_save.get(project)]
        for d in (project, os.path.join(project, "Ableton Project Info")):
            try:
                times.append(getattr(os.stat(d), "st_birthtime", None))
            except OSError:
                pass
        times = [t for t in times if t]
        return min(times) if times else None

    def _find_copy(self, con, g: dict) -> None:
        """Note a folder inside a project that already has every one of these files."""
        g["copy_of"], g["copy_project"], g["copy_pairs"] = None, None, []
        if g["in_project"]:
            return
        mine = {(norm_name(f["name"]), f["size"]): f["path"] for f in g["files"]}
        sizes = sorted({f["size"] for f in g["files"]})
        here = safety.norm(g["folder"])
        found = defaultdict(dict)  # folder -> {(name, size): path}
        q = "SELECT path, parent, name, size FROM files WHERE size IN (%s)" % ",".join("?" * len(sizes))
        for r in con.execute(q, sizes):
            key = (norm_name(r["name"]), r["size"])
            if key in mine and safety.norm(r["parent"]) != here:
                found[r["parent"]][key] = r["path"]
        for folder, hits in sorted(found.items(), key=lambda kv: -len(kv[1])):
            if len(hits) < len(mine):
                break
            proj = _project_of(folder, self.projects)
            if proj:
                g["copy_of"], g["copy_project"] = folder, proj
                g["copy_pairs"] = [(mine[k], hits[k]) for k in sorted(mine)]
                return

    def groups_for(self, project: str) -> list:
        return [g for g in self.groups if g["project"] == project]

    def group_for_folder(self, folder: str) -> dict | None:
        """A stem group that is this whole folder (not one of several in it)."""
        n = safety.norm(folder)
        hits = [g for g in self.groups if safety.norm(g["folder"]) == n]
        return max(hits, key=lambda g: len(g["files"])) if hits else None


_cache = {}
_hashes = {}
CHECK_COPY_BYTES = 4_000_000_000  # don't read more than this to check one copy


def copy_checked(g: dict) -> bool:
    """Are the files byte-for-byte the same as the filed copy? Never reads a file
    that's only in iCloud (that would download it)."""
    from .dupes import _full_hash
    pairs = g.get("copy_pairs") or []
    if not pairs or sum(os.path.getsize(a) for a, _ in pairs if os.path.exists(a)) * 2 > CHECK_COPY_BYTES:
        return False
    for pair in pairs:
        digests = []
        for path in pair:
            try:
                st = os.stat(path)
            except OSError:
                return False
            if getattr(st, "st_flags", 0) & safety.SF_DATALESS:
                return False
            key = (path, st.st_size, st.st_mtime)
            if key not in _hashes:
                _hashes[key] = _full_hash(path)
            digests.append(_hashes[key])
        if digests[0] is None or digests[0] != digests[1]:
            return False
    return True


def index(con) -> Index:
    key = tuple(sorted(db.meta(con).items()))
    runs_key = tuple(sorted((os.path.getmtime(d) for d in stem_prep_dirs() if os.path.isdir(d))))
    hit = _cache.get("index")
    if hit and hit[0] == (key, runs_key):
        return hit[1]
    idx = Index(con)
    _cache["index"] = ((key, runs_key), idx)
    return idx


def _summary(g: dict) -> dict:
    return {"folder": g["folder"], "prefix": g["prefix"], "count": len(g["files"]), "bytes": g["bytes"],
            "first": g["first"], "mix": g["mix"], "confidence": g["confidence"], "why": g["why"],
            "stem_prep": g["stem_prep"], "dataless": g["dataless"], "in_project": bool(g["in_project"]),
            "received": g.get("received", False), "copy_of": g.get("copy_of"),
            "tracks": g["tracks"][:40]}


# --- the project checklist ---------------------------------------------------
def attach_checklist(con, cfg: dict, projects: list) -> None:
    """Add 'checklist' and 'stem_groups' to each project in the Ableton overview."""
    from . import marks
    idx = index(con)
    exports_dir = (cfg.get("layout") or {}).get("exports") or config.DEFAULT_CONFIG["layout"]["exports"]
    no_master = marks.flagged("no_master")
    files_in = defaultdict(list)
    marker = "/" + exports_dir + "/Master/"
    by_path = {p["path"]: p["path"] for p in projects}
    for r in con.execute("SELECT path FROM files WHERE category='audio' AND path LIKE ?", ("%" + marker + "%",)):
        proj = r["path"][: r["path"].rfind(marker)]
        if proj in by_path:
            files_in[proj].append(r["path"])
    for p in projects:
        groups = idx.groups_for(p["path"])
        mine = [g for g in groups if not g["received"]]
        inside = [g for g in mine if g["in_project"]]
        elsewhere = [g for g in mine if not g["in_project"]]
        masters_elsewhere = []
        for s in p["sets"]:
            for b in s.get("bounces") or []:
                if audio_kind(b["name"]) == "master" and not safety.norm(b["path"]).startswith(safety.norm(p["path"]) + "/"):
                    if b["path"] not in masters_elsewhere:
                        masters_elsewhere.append(b["path"])
        if p["path"] in no_master:
            master = "not-needed"
        elif files_in[p["path"]]:
            master = "in"
        else:
            master = "elsewhere" if masters_elsewhere else "none"
        stems = "in" if inside else "elsewhere" if elsewhere else "none"
        self_contained = bool(p.get("movable")) if "movable" in p else p["status"] == "ok"
        p["checklist"] = {
            "self_contained": self_contained, "status": p["status"],
            "master": master, "masters_in": files_in[p["path"]][:6], "masters_elsewhere": masters_elsewhere[:6],
            "stems": stems,
            "organised": self_contained and master in ("in", "not-needed") and stems in ("in",) + (("none",) if master == "not-needed" else ()),
        }
        p["stem_groups"] = [_summary(g) for g in sorted(groups, key=lambda g: -g["first"])][:12]
    unmatched = [g for g in idx.groups if not g["project"]]
    return {"unmatched_groups": [_summary(g) for g in sorted(unmatched, key=lambda g: -g["first"])][:200],
            "groups": len(idx.groups), "runs": len(idx.runs), "has_tracks": idx.has_tracks}
