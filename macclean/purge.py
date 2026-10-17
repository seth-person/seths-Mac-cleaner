"""Things that are probably safe to get rid of, found from the last scan.

Each finding: {kind, title, path, alloc, risk, why, action}
  risk "safe"   - rebuilt automatically or provably redundant: fine to trash
                  without looking (these are what "Select all safe" picks)
  risk "review" - probably junk, but only you can tell: look first
  action "trash" / "trash-asd", or None for "look at it, but there's
         nothing to click" (e.g. the Trash itself, big old files)

Guards applied to everything: never a file an Ableton set uses, never
anything inside an Ableton project or a sound library, never something whose
parent folder is already listed.
"""
from __future__ import annotations

import os
import plistlib
import re
import time
import zipfile

from . import classify, config, safety

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

# Caches that are pure, rebuildable download/build caches. Everything else in
# ~/Library/Caches is "review": some apps keep offline media or state there.
SAFE_CACHE_HINTS = ("com.google.chrome", "com.brave.browser", "org.mozilla.firefox", "firefox",
                    "com.microsoft.edgemac", "com.operasoftware", "com.vivaldi", "homebrew", "pip",
                    "pypoetry", "yarn", "ms-playwright", "go-build", "node-gyp", "typescript",
                    "com.microsoft.vscode", "jetbrains", "adobe")
# Never suggested: system/sync state, and apps known to keep real content in "Caches".
SKIP_CACHE_HINTS = ("com.apple.", "cloudkit", "spotify", "splice", "ableton", "com.native-instruments",
                    "music", "itunes", "podcasts")

INSTALLER_MAX = 2_000_000_000  # bigger "installers" are usually sample libraries
MIN_SCREENSHOT_DAYS = 30


def _f(kind, title, path, alloc, risk, why, action="trash", **extra):
    return {"kind": kind, "group": GROUPS[kind], "title": title, "path": path, "alloc": alloc or 0,
            "risk": risk, "why": why, "action": action, **extra}


def is_encrypted_image(path: str) -> bool:
    """Encrypted .dmg files are usually personal vaults, not installers."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
            f.seek(-8, os.SEEK_END)
            tail = f.read(8)
    except OSError:
        return False
    return head == b"encrcdsa" or tail == b"cdsaencr"


def archive_matches_folder(archive: str, folder: str) -> bool:
    """True only if every file in the zip exists in the folder with the same size."""
    if not archive.lower().endswith(".zip"):
        return False
    try:
        with zipfile.ZipFile(archive) as zf:
            entries = [i for i in zf.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX/")
                       and not os.path.basename(i.filename).startswith("._")]
    except (OSError, zipfile.BadZipFile):
        return False
    if not entries:
        return False
    stem = os.path.basename(folder)
    for e in entries:
        name = e.filename
        # Either the zip holds "Folder/…" (extracted next to it) or its files directly.
        rel = name[len(stem) + 1:] if name.startswith(stem + "/") else name
        target = os.path.join(folder, rel)
        try:
            if os.path.getsize(target) != e.file_size:
                return False
        except OSError:
            return False
    return True


def _device_name(backup_dir: str) -> str | None:
    try:
        with open(os.path.join(backup_dir, "Info.plist"), "rb") as f:
            return plistlib.load(f).get("Device Name")
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None


def findings(con, cfg: dict) -> list:
    h = str(config.home())
    lib = os.path.join(h, "Library")
    caches = os.path.join(lib, "Caches")
    cloud = str(config.expand(cfg["cloud_root"], cfg))
    out = []
    now = time.time()
    inboxes = [str(p) for p in config.inbox_paths(cfg)]
    projects = safety.project_dirs(con)
    used = safety.used_by_sets(con)
    unchecked = safety.unchecked_sets(con)

    def dir_row(path):
        return con.execute("SELECT * FROM dirs WHERE path=?", (path,)).fetchone()

    def children(path, min_alloc=1_000_000):
        return con.execute("SELECT * FROM dirs WHERE parent=? AND alloc>=? ORDER BY alloc DESC",
                           (path, min_alloc)).fetchall()

    # App caches.
    for r in children(caches, 20_000_000):
        name = r["name"].casefold()
        if name.startswith(SKIP_CACHE_HINTS) or any(s in name for s in SKIP_CACHE_HINTS):
            continue
        if any(s in name for s in SAFE_CACHE_HINTS):
            out.append(_f("cache", r["name"], r["path"], r["alloc"], "safe",
                          "A download or build cache that's rebuilt automatically. Quit the app first."))
        else:
            out.append(_f("cache", r["name"], r["path"], r["alloc"], "review",
                          "Usually rebuildable, but some apps keep offline files or settings here. "
                          "Quit the app first, and skip it if you're not sure what it is."))
    live_cache_roots = [caches, os.path.join(h, "Music", "Ableton")]
    for r in con.execute("SELECT * FROM dirs WHERE name='Decoding Cache' AND alloc>=1e6"):
        if safety.inside_any(r["path"], live_cache_roots):
            out.append(_f("ableton", "Ableton decoding cache", r["path"], r["alloc"], "safe",
                          "Live re-creates these when it plays compressed samples (MP3, FLAC). Quit Live first."))

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
            device = _device_name(c["path"]) or "a device"
            out.append(_f("backup", f"Backup of {device}", c["path"], c["alloc"], "review",
                          f"Last changed {_ago(c['mtime'], now)}. It's the only copy if that device "
                          "doesn't back up to iCloud. Only remove it if it does, or the device is gone."))

    # Inboxes: installers, partial downloads, unzipped archives, screenshots.
    for inbox in inboxes:
        for f in con.execute("SELECT * FROM files WHERE parent=?", (inbox,)):
            # "Age" = since it arrived here: copies and AirDrops keep an old modified date.
            age = (now - max(f["mtime"], f["birth"] or 0)) / 86400
            if f["category"] == "installer":
                if age <= 7 or f["size"] > INSTALLER_MAX or is_encrypted_image(f["path"]) \
                        or re.search(config.PLUGIN_VENDORS, f["name"], re.I):
                    continue  # music-software installers are worth keeping: Catch-alls files them
                out.append(_f("installer", f["name"], f["path"], f["alloc"], "review",
                              f"Installer that arrived {_ago(now - age * 86400, now)}. If it's installed and you "
                              "can download it again, it can go. Keep installers for plugins you paid for once "
                              "or old versions you rely on."))
            elif f["ext"] in classify.PARTIAL_DOWNLOAD_EXTS and age > 1:
                out.append(_f("installer", f["name"], f["path"], f["alloc"], "safe",
                              "A download that never finished; it can't be opened."))
            elif f["category"] == "archive":
                stem = f["name"][: -len(f["ext"])] if f["ext"] else f["name"]
                if stem.endswith(".tar"):
                    stem = stem[:-4]
                folder = os.path.join(inbox, stem)
                if not os.path.isdir(folder):
                    continue
                if archive_matches_folder(f["path"], folder):
                    out.append(_f("archive", f["name"], f["path"], f["alloc"], "safe",
                                  f"Everything in it is already in the “{stem}” folder next to it, unchanged."))
                else:
                    out.append(_f("archive", f["name"], f["path"], f["alloc"], "review",
                                  f"There's a “{stem}” folder next to it, but it doesn't match the archive exactly "
                                  "(changed since, or only partly unpacked). Check before removing."))
            elif f["name"].startswith(("Screenshot", "Screen Shot", "Screen Recording")) \
                    and age > MIN_SCREENSHOT_DAYS:
                out.append(_f("screenshot", f["name"], f["path"], f["alloc"], "review",
                              f"Taken {_ago(now - age * 86400, now)}. Screenshots can hold serial numbers or "
                              "receipts, so have a look first."))

    # Ableton: analysis files and auto-backups (never inside Packs or the Live library).
    rows = con.execute("SELECT parent, SUM(alloc) a, COUNT(*) n FROM files WHERE ext='.asd' GROUP BY parent "
                       "HAVING a >= 5e6 ORDER BY a DESC LIMIT 200").fetchall()
    for r in rows:
        if safety.in_sound_library(r["parent"]):
            continue
        out.append(_f("ableton", f"{r['n']} .asd files in {os.path.basename(r['parent'])}", r["parent"], r["a"],
                      "review", "Waveform and warp data. Live re-analyses the samples when it loads them, but "
                      "warp markers you saved as a sample's default are lost.", action="trash-asd"))
    for r in con.execute("SELECT * FROM dirs WHERE name='Backup' AND alloc>=5e6 ORDER BY alloc DESC"):
        if con.execute("SELECT 1 FROM dirs WHERE path=? AND kind='ableton-project'", (r["parent"],)).fetchone():
            out.append(_f("ableton", "Auto-backups of " + os.path.basename(r["parent"]), r["path"], r["alloc"],
                          "review", "Older versions of the set that Live saved automatically. "
                          "Keep them if you might want to roll back."))

    # Duplicates: keep the copy a set uses, then the organised (iCloud/Projects)
    # one, then any copy outside Downloads/Desktop, then the oldest.
    organised = [cloud, str(config.expand(cfg["ableton_root"], cfg))]
    groups = {}
    for d in con.execute("SELECT d.*, f.birth, f.category FROM dupes d LEFT JOIN files f ON f.path = d.path "
                         "ORDER BY grp"):
        groups.setdefault(d["grp"], []).append(d)
    for gid, members in groups.items():
        if unchecked and any(m["category"] == "audio" for m in members):
            continue  # some sets couldn't be read; they might use any of these copies
        ranked = sorted(members, key=lambda m: (safety.norm(m["path"]) not in used,
                                                not safety.inside_any(m["path"], organised),
                                                _in_any(m["path"], inboxes), m["birth"] or 0))
        keep = ranked[0]["path"]
        keep_used = safety.norm(keep) in used
        for m in ranked[1:]:
            if _in_any(m["path"], [cloud]):
                why = (f"Identical to {_short(keep, h)}. This copy is in iCloud Drive, so removing it "
                       "removes it from your other devices too.")
            else:
                why = f"Identical to {_short(keep, h)}."
            if keep_used and _in_any(keep, inboxes):
                why += (" That copy is kept because an Ableton set uses it. Open the set in Live and use "
                        "Collect All and Save, so it no longer depends on Downloads.")
            elif keep_used:
                why += " That copy is kept because an Ableton set uses it."
            out.append(_f("dupe", os.path.basename(m["path"]), m["path"], m["size"], "review", why,
                          keep=keep, dupe_group=gid))

    # Large, untouched files: worth knowing about, but not for the Trash button.
    cutoff = now - 180 * 86400
    for f in con.execute("SELECT * FROM files WHERE alloc>=500e6 AND mtime<? AND category NOT IN "
                         "('library','system') AND dataless=0 ORDER BY alloc DESC LIMIT 80", (cutoff,)):
        p = f["path"]
        if p.startswith(lib + os.sep) or "/." in p or safety.in_sound_library(p) \
                or safety.inside_any(p, projects):
            continue
        out.append(_f("stale", f["name"], p, f["alloc"], "review",
                      f"Last changed {_ago(f['mtime'], now)}. If you still want it, an external drive or iCloud "
                      "(with Optimise Mac Storage on) frees the space without losing it.", action=None))

    r = dir_row(os.path.join(h, ".Trash"))
    if r and r["alloc"] > 0:
        out.append(_f("trash", "Your Trash", r["path"], r["alloc"], "safe",
                      "Empty the Trash in Finder to actually free this space.", action=None))

    # Guards, in order: nothing a set uses, nothing inside a project, nothing listed twice,
    # nothing whose parent folder is already listed.
    kept, seen = [], set()
    for item in out:
        n = safety.norm(item["path"])
        if item["action"] and (n in used or (item["kind"] != "ableton" and safety.inside_any(item["path"], projects))):
            continue
        if n in seen:
            continue
        seen.add(n)
        kept.append(item)
    actionable = [i["path"] for i in kept if i["action"]]
    return [i for i in kept if not (i["action"] and safety.inside_any(i["path"], [p for p in actionable
                                                                                  if p != i["path"]]))]


def summary(con, cfg: dict, items: list) -> dict:
    unchecked = safety.unchecked_sets(con)
    return {
        "safe": sum(i["alloc"] for i in items if i["action"] and i["risk"] == "safe"),
        "review": sum(i["alloc"] for i in items if i["action"] and i["risk"] == "review"),
        "unchecked_sets": len(unchecked),
        "unchecked_examples": [u["path"] for u in unchecked[:5]],
    }


def trash_asd(folder: str, cfg: dict) -> list:
    """Trash the .asd files in one folder as a single, single-undo action."""
    from . import actions
    paths = [os.path.join(folder, n) for n in sorted(os.listdir(folder)) if n.lower().endswith(".asd")]
    if not paths:
        return [{"ok": False, "path": folder, "error": "No .asd files left in that folder"}]
    try:
        entry = actions.trash_group(paths, f".asd files from {os.path.basename(folder)}", cfg)
        return [{"ok": True, "path": folder, **entry}]
    except (actions.ActionError, OSError) as e:
        return [{"ok": False, "path": folder, "error": str(e)}]


def _in_any(path, roots):
    return any(path.startswith(r + os.sep) for r in roots)


def _short(path, h):
    if "/" + config.ICLOUD_REL + "/" in path:
        return "iCloud Drive/" + path.split("/" + config.ICLOUD_REL + "/", 1)[1]
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
