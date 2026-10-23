"""Projects you've marked as important, and your tags, kept in ~/.macclean/marks.json.

Marks are keyed by the project's folder path. When Mac Cleaner moves a
project the mark moves with it; if you move it yourself in Finder, the mark
is matched again by folder name. Nothing is written into the projects.

Tags have a name (unique, ignoring case), a kind (e.g. "Album / EP", "Type")
and a colour number. A project's tags are listed by name.
"""
from __future__ import annotations

import json
import os
import threading
import time

from . import config

_lock = threading.Lock()


def _path():
    return config.app_dir() / "marks.json"


def load() -> dict:
    try:
        data = json.loads(_path().read_text())
    except (OSError, ValueError):
        data = {}
    data.setdefault("important", {})
    return data


def _save(data: dict) -> None:
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, _path())


def set_important(path: str, on: bool) -> None:
    with _lock:
        data = load()
        if on:
            data["important"][path] = {"since": time.time(), "name": os.path.basename(path)}
        else:
            data["important"].pop(path, None)
        _save(data)


def important_lookup() -> tuple:
    """(by_path, by_name) for matching projects to marks."""
    imp = load()["important"]
    return set(imp), {v.get("name") or os.path.basename(k) for k, v in imp.items()}


def is_important(path: str, lookup: tuple) -> bool:
    by_path, by_name = lookup
    return path in by_path or os.path.basename(path) in by_name


def moved(src: str, dst: str) -> None:
    """Called after Mac Cleaner moves something: carry marks along."""
    with _lock:
        data = load()
        changed = False
        for k in list(data["important"]):
            if k == src or k.startswith(src + os.sep):
                v = data["important"].pop(k)
                new = dst + k[len(src):]
                v["name"] = os.path.basename(new)
                data["important"][new] = v
                changed = True
        tagged = data.get("tags") or {}
        for k in list(tagged):
            if k == src or k.startswith(src + os.sep):
                v = tagged.pop(k)
                new = dst + k[len(src):]
                v["name"] = os.path.basename(new)
                tagged[new] = v
                changed = True
        for flags in (data.get("flags") or {}).values():
            for k in list(flags):
                if k == src or k.startswith(src + os.sep):
                    flags[dst + k[len(src):]] = flags.pop(k)
                    changed = True
        if changed:
            _save(data)


def set_flag(path: str, flag: str, on: bool) -> None:
    """Per-project flags, e.g. "no_master" for sketches that don't need a final master."""
    with _lock:
        data = load()
        flags = data.setdefault("flags", {}).setdefault(flag, {})
        if on:
            flags[path] = {"since": time.time()}
        else:
            flags.pop(path, None)
        _save(data)


def flagged(flag: str) -> set:
    return set((load().get("flags") or {}).get(flag) or {})


# --- tags ----------------------------------------------------------------------
TAG_KINDS = ["Album / EP", "Type", "Status", "Collab", "Other"]
MAX_TAG_LEN = 40


def _clean_tag(name) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise ValueError("Give the tag a name")
    if len(name) > MAX_TAG_LEN:
        raise ValueError(f"Tag names can be up to {MAX_TAG_LEN} characters")
    return name


def _find(defs: list, name: str) -> dict | None:
    key = name.casefold()
    return next((d for d in defs if d["name"].casefold() == key), None)


def tag_defs() -> list:
    return list(load().get("tag_defs") or [])


def _new_def(defs: list, name: str, kind: str | None = None, color: int | None = None) -> dict:
    d = {"name": name, "kind": " ".join(str(kind or "Other").split()) or "Other",
         "color": int(color) if color is not None else (len(defs) % 8) + 1}
    defs.append(d)
    return d


def create_tag(name: str, kind: str | None = None, color: int | None = None) -> dict:
    name = _clean_tag(name)
    with _lock:
        data = load()
        defs = data.setdefault("tag_defs", [])
        if _find(defs, name):
            raise ValueError(f"There's already a tag called “{name}”")
        d = _new_def(defs, name, kind, color)
        _save(data)
        return d


def update_tag(name: str, new_name: str | None = None, kind: str | None = None, color: int | None = None) -> dict:
    """Rename (everywhere it's used), change its kind or colour."""
    with _lock:
        data = load()
        defs = data.setdefault("tag_defs", [])
        d = _find(defs, name)
        if not d:
            raise ValueError(f"No tag called “{name}”")
        if new_name is not None:
            new_name = _clean_tag(new_name)
            clash = _find(defs, new_name)
            if clash and clash is not d:
                raise ValueError(f"There's already a tag called “{new_name}”")
            old = d["name"]
            d["name"] = new_name
            for v in (data.get("tags") or {}).values():
                v["tags"] = [new_name if t.casefold() == old.casefold() else t for t in v.get("tags", [])]
        if kind is not None:
            d["kind"] = " ".join(str(kind).split()) or "Other"
        if color is not None:
            d["color"] = max(1, min(8, int(color)))
        _save(data)
        return d


def delete_tag(name: str) -> None:
    """Remove a tag from the list and from every project (the projects aren't touched)."""
    with _lock:
        data = load()
        key = name.casefold()
        data["tag_defs"] = [d for d in data.get("tag_defs") or [] if d["name"].casefold() != key]
        tagged = data.get("tags") or {}
        for k in list(tagged):
            tagged[k]["tags"] = [t for t in tagged[k].get("tags", []) if t.casefold() != key]
            if not tagged[k]["tags"]:
                tagged.pop(k)
        _save(data)


def _resolve(defs: list, names) -> list:
    """Known tag names in their stored spelling; unknown ones are created (kind Other)."""
    out = []
    for n in names or []:
        n = _clean_tag(n)
        d = _find(defs, n) or _new_def(defs, n)
        if d["name"] not in out:
            out.append(d["name"])
    return out


def set_tags(path: str, names: list) -> list:
    """Replace a project's tags."""
    with _lock:
        data = load()
        defs = data.setdefault("tag_defs", [])
        tags = _resolve(defs, names)
        tagged = data.setdefault("tags", {})
        if tags:
            tagged[path] = {"name": os.path.basename(path), "tags": tags}
        else:
            tagged.pop(path, None)
        _save(data)
        return tags


def _entry(tagged: dict, path: str) -> dict:
    """A project's tag entry, taking over one kept under its folder name (moved in Finder)."""
    if path not in tagged:
        name = os.path.basename(path)
        old = next((k for k, v in tagged.items() if (v.get("name") or os.path.basename(k)) == name
                    and not os.path.exists(k)), None)
        tagged[path] = tagged.pop(old) if old else {"name": name, "tags": []}
    return tagged[path]


def add_tags(paths: list, names: list) -> list:
    """Add tags to several projects at once (their other tags stay)."""
    with _lock:
        data = load()
        defs = data.setdefault("tag_defs", [])
        tags = _resolve(defs, names)
        tagged = data.setdefault("tags", {})
        for p in paths:
            cur = _entry(tagged, p)
            cur["tags"] += [t for t in tags if t not in cur["tags"]]
        _save(data)
        return tags


def remove_tags(paths: list, names: list) -> list:
    """Take tags off several projects at once (their other tags stay)."""
    with _lock:
        data = load()
        gone = {n.casefold() for n in names if isinstance(n, str)}
        tagged = data.setdefault("tags", {})
        for p in paths:
            cur = _entry(tagged, p)
            cur["tags"] = [t for t in cur["tags"] if t.casefold() not in gone]
            if not cur["tags"]:
                tagged.pop(p, None)
        _save(data)
        return sorted(gone)


def tags_lookup() -> tuple:
    """(by_path, by_folder_name) so projects moved in Finder keep their tags."""
    tagged = load().get("tags") or {}
    by_path = {k: v.get("tags", []) for k, v in tagged.items()}
    by_name = {}
    for k, v in tagged.items():
        by_name.setdefault(v.get("name") or os.path.basename(k), v.get("tags", []))
    return by_path, by_name


def tags_for(path: str, lookup: tuple) -> list:
    by_path, by_name = lookup
    if path in by_path:
        return list(by_path[path])
    return list(by_name.get(os.path.basename(path), []))
