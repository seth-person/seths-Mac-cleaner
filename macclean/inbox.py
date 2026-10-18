"""Triage of the catch-all folders (Downloads, Desktop by default).

Reads the folders live (not from the scan) so the list is always current, then
runs each top-level item through the rules in config.json to suggest where it
should go.
"""
from __future__ import annotations

import os
import re
import time
from collections import Counter
from datetime import datetime

from . import ableton, classify, config, safety

FOLDER_SIZE_FILE_LIMIT = 20000


def _folder_info(path: str):
    """(size_on_disk, newest_mtime, dominant category, file count) for a folder."""
    size = 0
    newest = 0.0
    by_cat = Counter()
    n = 0
    for dirpath, dirnames, filenames in os.walk(path):
        # Don't count inside packages; treat them as one item of their category.
        for d in list(dirnames):
            if os.path.splitext(d)[1].lower() in classify.PACKAGE_SUFFIXES:
                dirnames.remove(d)
                by_cat[classify.category_for_name(d, True)] += 1
        for fn in filenames:
            n += 1
            if n > FOLDER_SIZE_FILE_LIMIT:
                return size, newest, _dominant(by_cat), n
            try:
                st = os.lstat(os.path.join(dirpath, fn))
            except OSError:
                continue
            a = getattr(st, "st_blocks", 0) * 512 or st.st_size
            size += a
            newest = max(newest, st.st_mtime)
            cat = classify.category_for_name(fn)
            if fn.startswith("."):
                continue
            by_cat[cat] += a or 1
    return size, newest, _dominant(by_cat), n


def _dominant(by_cat: Counter) -> str:
    by_cat.pop("other", None)
    if not by_cat:
        return "other"
    return by_cat.most_common(1)[0][0]


def describe(path: str) -> dict:
    st = os.lstat(path)
    name = os.path.basename(path)
    is_dir = os.path.isdir(path) and not os.path.islink(path)
    ext = os.path.splitext(name)[1].lower()
    added = getattr(st, "st_birthtime", None) or st.st_mtime
    item = {"path": path, "name": name, "ext": ext, "is_dir": is_dir, "mtime": st.st_mtime, "added": added}
    if is_dir and classify.is_ableton_project(path):
        size, newest, _, n = _folder_info(path)
        item.update(kind="ableton-project", category="ableton", size=size, files=n, mtime=newest or st.st_mtime)
    elif is_dir and ext in classify.PACKAGE_SUFFIXES:
        size, newest, _, n = _folder_info(path)
        item.update(kind="package", category=classify.category_for_name(name, True), size=size, files=n)
    elif is_dir:
        size, newest, cat, n = _folder_info(path)
        item.update(kind="folder", category=cat, size=size, files=n, mtime=newest or st.st_mtime)
    else:
        cat = classify.classify_file(path) if not name.endswith(".icloud") else "other"
        size = getattr(st, "st_blocks", 0) * 512 or st.st_size
        item.update(kind="file", category=cat, size=size, files=1)
    if is_dir:
        added = item["mtime"]  # a folder's own dates change whenever anything inside does
    # "Age" is how long since you last did anything with it.
    item["age_days"] = (time.time() - max(item["mtime"], added)) / 86400
    return item


def _matches(rule: dict, item: dict) -> bool:
    w = rule.get("when", {})
    if rule.get("enabled") is False:
        return False
    if rule.get("action") == "trash" and item["kind"] != "file":
        return False  # a folder may hold things worth keeping (license keys, manuals...)
    if "category" in w and item["category"] not in w["category"]:
        return False
    if "ext" in w and item["ext"] not in [e.lower() for e in w["ext"]]:
        return False
    if "kind" in w and item["kind"] not in w["kind"]:
        return False
    if "name_regex" in w and not re.search(w["name_regex"], item["name"], re.I):
        return False
    if "older_than_days" in w and item["age_days"] < float(w["older_than_days"]):
        return False
    if "larger_than_mb" in w and item["size"] < float(w["larger_than_mb"]) * 1e6:
        return False
    return True


def suggest(item: dict, cfg: dict) -> dict | None:
    for rule in cfg.get("rules", []):
        try:
            if not _matches(rule, item):
                continue
        except re.error:
            continue
        sug = {"rule": rule.get("name", ""), "action": rule["action"], "auto": bool(rule.get("auto"))}
        if rule["action"] == "trash":
            sug["risk"] = rule.get("risk", "review")
        if rule["action"] == "move":
            dt = datetime.fromtimestamp(item["mtime"])
            sug["dest"] = str(config.expand(rule["dest"], cfg, year=dt.year, month=f"{dt.month:02d}",
                                            category=item["category"]))
        return sug
    return None


def _extracted_copy(item: dict, inbox: str):
    """For an archive with a same-named folder next to it: 'match', 'differs' or None."""
    if item["category"] != "archive" or item["is_dir"]:
        return None
    stem = item["name"]
    for ext in (".tar.gz", ".tar.bz2", ".tar.xz") + (item["ext"],):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break
    folder = os.path.join(inbox, stem)
    if not os.path.isdir(folder):
        return None
    from .purge import archive_matches_folder
    return "match" if archive_matches_folder(item["path"], folder) else "differs"


def mark_used_by_sets(data: dict, con, cfg: dict | None = None) -> None:
    """Items an Ableton set or preset elsewhere depends on are kept where they are,
    whatever the rules say: moving them would break the set. Duplicates of
    something already filed are suggested for the Trash instead of a move."""
    if con is None:
        return
    from .purge import dupe_plan
    used = safety.UsedIndex(con)
    dupes = dupe_plan(con, cfg or config.load_config(), used)
    for ib in data["inboxes"]:
        for item in ib["items"]:
            users = used.users(item["path"])
            if users:
                item["used_by"] = users
                item["suggestion"] = {"rule": "Used by Ableton", "action": "keep", "auto": False,
                                      "reason": ableton.keep_advice(users[0])}
                continue
            d = dupes.get(item["path"])
            if d and d["trashable"]:
                item["suggestion"] = {"rule": "Duplicate", "action": "trash", "auto": False, "risk": "review",
                                      "reason": f"an identical copy is already in {d['keep_short']}"}


def list_inboxes(cfg: dict | None = None) -> dict:
    cfg = cfg or config.load_config()
    stale = float(cfg.get("stale_days", 21))
    active = {str(config.expand(p, cfg)) for p in cfg.get("active_inboxes", [])}
    out = []
    for inbox in config.inbox_paths(cfg):
        is_active = str(inbox) in active
        items = []
        if inbox.is_dir():
            try:
                entries = [e for e in os.scandir(inbox) if not e.name.startswith(".")
                           and e.name not in ("Icon\r", "$RECYCLE.BIN")]
            except OSError as e:
                out.append({"path": str(inbox), "error": str(e), "items": []})
                continue
            for e in entries:
                try:
                    item = describe(e.path)
                except OSError:
                    continue
                item["stale"] = item["age_days"] >= stale
                extracted = _extracted_copy(item, str(inbox))
                if is_active and not item["stale"]:
                    item["suggestion"] = {"rule": "Still active", "action": "keep", "auto": False,
                                          "reason": f"touched in the last {int(stale)} days"}
                elif extracted == "match":
                    item["suggestion"] = {"rule": "Already unzipped", "action": "trash", "auto": False,
                                          "risk": "safe", "reason": "everything in it is in the folder next to it"}
                else:
                    item["suggestion"] = suggest(item, cfg)
                items.append(item)
        items.sort(key=lambda i: -i["size"])
        out.append({
            "path": str(inbox), "name": inbox.name, "items": items,
            "count": len(items), "size": sum(i["size"] for i in items),
            "stale": sum(1 for i in items if i["stale"]), "active": is_active,
        })
    return {"inboxes": out, "stale_days": stale}


def destinations(con, cfg: dict) -> list:
    """Folders worth offering as destinations: everything 1-3 levels into iCloud,
    plus the destinations the rules already use."""
    cloud = str(config.expand(cfg["cloud_root"], cfg))
    dests = set()
    if con is not None:
        for r in con.execute("SELECT path FROM dirs WHERE (path = ? OR path LIKE ?) AND depth <= "
                             "(SELECT depth FROM dirs WHERE path = ?) + 3 AND kind = 'dir'",
                             (cloud, cloud + "/%", cloud)):
            if "/." not in r["path"][len(cloud):]:
                dests.add(r["path"])
    else:
        for dirpath, dirnames, _ in os.walk(cloud):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            if dirpath[len(cloud):].count(os.sep) >= 3:
                dirnames[:] = []
            dests.add(dirpath)
    now = datetime.now()
    for rule in cfg.get("rules", []):
        if rule.get("dest"):
            dests.add(str(config.expand(rule["dest"], cfg, year=now.year, month=f"{now.month:02d}",
                                        category="")))
    root = str(config.expand(cfg["ableton_root"], cfg))
    for b in cfg.get("ableton_buckets", []):
        dests.add(os.path.join(root, b))
    return sorted(dests, key=str.lower)


def autosort(cfg: dict | None = None, dry_run: bool = True) -> list:
    """Apply only the suggestions from rules marked "auto": true."""
    from . import actions
    cfg = cfg or config.load_config()
    todo = []
    for inbox in list_inboxes(cfg)["inboxes"]:
        for item in inbox["items"]:
            s = item.get("suggestion")
            if s and s.get("auto") and s["action"] in ("move", "trash"):
                todo.append({"path": item["path"], "action": s["action"], "dest": s.get("dest"),
                             "note": "autosort: " + s["rule"]})
    return actions.apply(todo, cfg, dry_run=dry_run)
