"""Projects you've marked as important, kept in ~/.macclean/marks.json.

Marks are keyed by the project's folder path. When Mac Cleaner moves a
project the mark moves with it; if you move it yourself in Finder, the mark
is matched again by folder name.
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
