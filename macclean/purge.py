"""Things that are probably safe to get rid of, found from the last scan.

Each finding: {kind, title, path, alloc, risk, why, action}
  risk "safe"   - regenerated automatically or obviously leftover
  risk "review" - likely junk, but look before you trash it
  action "trash" or None (informational, e.g. the Trash itself)
"""
from __future__ import annotations

import os
import time

from . import classify, config

GROUPS = {
    "cache": "App caches",
    "dev": "Developer leftovers",
    "installer": "Installers & partial downloads",
    "archive": "Archives you've already unzipped",
    "dupe": "Duplicate files",
    "ableton": "Ableton leftovers",
    "stale": "Big files you haven't touched in 6+ months",
    "backup": "Device backups",
    "screenshot": "Old screenshots",
    "trash": "Already in the Trash",
}


def _f(kind, title, path, alloc, risk, why, action="trash", **extra):
    return {"kind": kind, "group": GROUPS[kind], "title": title, "path": path, "alloc": alloc or 0,
            "risk": risk, "why": why, "action": action, **extra}


def findings(con, cfg: dict) -> list:
    h = str(config.home())
    lib = os.path.join(h, "Library")
    out = []
    now = time.time()
    inboxes = [str(p) for p in config.inbox_paths(cfg)]

    def dir_row(path):
        return con.execute("SELECT * FROM dirs WHERE path=?", (path,)).fetchone()

    def children(path, min_alloc=1_000_000):
        return con.execute("SELECT * FROM dirs WHERE parent=? AND alloc>=? ORDER BY alloc DESC",
                           (path, min_alloc)).fetchall()

    # App caches: everything directly inside ~/Library/Caches is rebuildable.
    for r in children(os.path.join(lib, "Caches"), 20_000_000):
        out.append(_f("cache", r["name"], r["path"], r["alloc"], "safe",
                      "Apps rebuild their caches automatically. Quit the app first."))
    for r in con.execute("SELECT * FROM dirs WHERE name IN ('Decoding Cache', 'Ableton Cache') AND alloc>=1e6"):
        out.append(_f("ableton", "Ableton decoding cache", r["path"], r["alloc"], "safe",
                      "Live re-decodes compressed samples (mp3/flac) on demand."))

    dev_paths = [
        ("Developer/Xcode/DerivedData", "Xcode DerivedData", "safe", "Build products; Xcode recreates them."),
        ("Developer/Xcode/iOS DeviceSupport", "iOS DeviceSupport", "safe", "Re-downloaded when a device connects."),
        ("Developer/CoreSimulator/Caches", "Simulator caches", "safe", "Rebuilt by Xcode."),
        ("Developer/Xcode/Archives", "Xcode archives", "review", "Old app builds; keep ones you may need to symbolicate."),
    ]
    for rel, title, risk, why in dev_paths:
        r = dir_row(os.path.join(lib, rel))
        if r and r["alloc"] > 50_000_000:
            out.append(_f("dev", title, r["path"], r["alloc"], risk, why))
    for r in con.execute("SELECT * FROM dirs WHERE name='node_modules' AND alloc>=50e6 "
                         "AND parent NOT LIKE '%/node_modules%' ORDER BY alloc DESC LIMIT 100"):
        if r["path"].startswith(lib + os.sep):
            continue
        out.append(_f("dev", "node_modules in " + os.path.basename(r["parent"]), r["path"], r["alloc"],
                      "review", "Reinstalled with `npm install`; only matters for projects you still run."))

    r = dir_row(os.path.join(lib, "Application Support", "MobileSync", "Backup"))
    if r:
        for c in children(r["path"], 100_000_000):
            out.append(_f("backup", "iPhone/iPad backup " + c["name"][:8], c["path"], c["alloc"], "review",
                          f"Last changed {_ago(c['mtime'], now)}. Only needed if you restore that device "
                          "from this Mac rather than iCloud."))

    # Inboxes: installers, partial downloads, unzipped archives, screenshots.
    for inbox in inboxes:
        for f in con.execute("SELECT * FROM files WHERE parent=?", (inbox,)):
            age = (now - f["mtime"]) / 86400
            if f["category"] == "installer" and age > 3:
                out.append(_f("installer", f["name"], f["path"], f["alloc"], "safe",
                              f"Disk image/installer downloaded {_ago(f['mtime'], now)}; "
                              "the app is installed or you can download it again."))
            elif f["ext"] in classify.PARTIAL_DOWNLOAD_EXTS and age > 1:
                out.append(_f("installer", f["name"], f["path"], f["alloc"], "safe",
                              "An interrupted download; it can't be opened."))
            elif f["category"] == "archive":
                stem = f["name"][: -len(f["ext"])] if f["ext"] else f["name"]
                if stem.endswith(".tar"):
                    stem = stem[:-4]
                if dir_row(os.path.join(inbox, stem)):
                    out.append(_f("archive", f["name"], f["path"], f["alloc"], "safe",
                                  f"Already extracted to “{stem}” next to it."))
            elif f["name"].startswith(("Screenshot", "Screen Shot", "Screen Recording")) and age > 30:
                out.append(_f("screenshot", f["name"], f["path"], f["alloc"], "review",
                              f"Taken {_ago(f['mtime'], now)}."))

    # Ableton: analysis files and auto-backups.
    rows = con.execute("SELECT parent, SUM(alloc) a, COUNT(*) n FROM files WHERE ext='.asd' GROUP BY parent "
                       "HAVING a >= 5e6 ORDER BY a DESC LIMIT 200").fetchall()
    for r in rows:
        out.append(_f("ableton", f"{r['n']} .asd analysis files", r["parent"], r["a"], "safe",
                      "Live recreates .asd files when it loads the sample; they just cache waveforms.",
                      action="trash-asd"))
    for r in con.execute("SELECT * FROM dirs WHERE name='Backup' AND alloc>=5e6 ORDER BY alloc DESC"):
        if con.execute("SELECT 1 FROM dirs WHERE path=? AND kind='ableton-project'", (r["parent"],)).fetchone():
            out.append(_f("ableton", "Auto-backups of " + os.path.basename(r["parent"]), r["path"], r["alloc"],
                          "review", "Older versions of the set that Live saved automatically. "
                          "Keep them if you might want to roll back."))

    # Duplicates: suggest trashing all but one copy, preferring to keep the
    # organised (non-inbox) one.
    used_by_sets = {r[0] for r in con.execute("SELECT ref_path FROM ableton_refs")}
    groups = {}
    for d in con.execute("SELECT * FROM dupes ORDER BY grp"):
        groups.setdefault(d["grp"], []).append(d)
    for gid, members in groups.items():
        paths = sorted((m["path"] for m in members),
                       key=lambda p: (p not in used_by_sets, _in_any(p, inboxes), len(p)))
        keep = paths[0]
        for p in paths[1:]:
            out.append(_f("dupe", os.path.basename(p), p, members[0]["size"], "review",
                          f"Identical to {_short(keep, h)}"
                          + (" (kept because an Ableton set uses it)" if keep in used_by_sets else ""),
                          keep=keep, dupe_group=gid))

    # Large, untouched user files.
    cutoff = now - 180 * 86400
    for f in con.execute("SELECT * FROM files WHERE alloc>=500e6 AND mtime<? AND category NOT IN "
                         "('library','system') AND dataless=0 ORDER BY alloc DESC LIMIT 50", (cutoff,)):
        if f["path"].startswith(lib + os.sep) or "/." in f["path"]:
            continue
        out.append(_f("stale", f["name"], f["path"], f["alloc"], "review",
                      f"Last modified {_ago(f['mtime'], now)}. If it matters, it might belong in iCloud "
                      "with “Optimise Mac Storage” on, or on an external drive."))

    r = dir_row(os.path.join(h, ".Trash"))
    if r and r["alloc"] > 0:
        out.append(_f("trash", "Your Trash", r["path"], r["alloc"], "safe",
                      "Empty the Trash in Finder to actually free this space.", action=None))

    # Never suggest trashing a file an Ableton set still points at.
    used = {}
    for r in con.execute("SELECT ref_path, set_path FROM ableton_refs"):
        used.setdefault(r["ref_path"], r["set_path"])
    kept = []
    for item in out:
        if item["action"] and item["path"] in used:
            continue
        kept.append(item)
    out = kept

    # Avoid listing something twice (e.g. a dupe that's also an installer).
    seen, unique = set(), []
    for item in out:
        if item["path"] in seen:
            continue
        seen.add(item["path"])
        unique.append(item)
    return unique


def trash_asd(folder: str, cfg: dict) -> list:
    """Trash only the .asd files in a folder (used for the 'trash-asd' action)."""
    from . import actions
    items = [{"path": os.path.join(folder, n), "action": "trash", "note": "asd cleanup"}
             for n in os.listdir(folder) if n.lower().endswith(".asd")]
    return actions.apply(items, cfg)


def _in_any(path, roots):
    return any(path.startswith(r + os.sep) for r in roots)


def _short(path, h):
    return "~" + path[len(h):] if path.startswith(h) else path


def _ago(ts, now):
    days = (now - ts) / 86400
    if days < 1:
        return "today"
    if days < 60:
        return f"{int(days)} days ago"
    if days < 730:
        return f"{int(days / 30)} months ago"
    return f"{days / 365:.0f} years ago"
