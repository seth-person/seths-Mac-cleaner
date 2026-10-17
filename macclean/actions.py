"""File operations. Nothing is ever deleted outright.

"trash" moves the item into ~/.Trash (so emptying the Trash stays your call),
"move" never overwrites (a " 2" suffix is added on name clashes), and every
operation is appended to actions.jsonl so it can be undone from the dashboard.
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path

from . import config


class ActionError(Exception):
    pass


def _protected(cfg: dict) -> set:
    h = config.home()
    paths = {h, h / "Library", h / "Desktop", h / "Downloads", h / "Documents", h / "Music",
             h / "Pictures", h / "Movies", h / ".Trash", config.expand(cfg["cloud_root"], cfg),
             config.expand(cfg["ableton_root"], cfg)}
    paths.update(config.inbox_paths(cfg))
    return {os.path.realpath(p) for p in paths}


def _check_source(src: Path, cfg: dict) -> Path:
    src = Path(os.path.abspath(os.path.expanduser(str(src))))
    if not os.path.lexists(src):
        raise ActionError(f"{src} no longer exists")
    real = os.path.realpath(src) if not src.is_symlink() else str(src)
    if not real.startswith(str(os.path.realpath(config.home())) + os.sep):
        raise ActionError(f"{src} is outside your home folder; macclean only touches your own files")
    if real in _protected(cfg):
        raise ActionError(f"{src} is a top-level folder and can't be moved or trashed")
    return src


def _unique(target: Path) -> Path:
    if not os.path.lexists(target):
        return target
    stem, suffix = target.stem, target.suffix
    if target.is_dir() and not suffix.lower() in (".app", ".logicx"):
        stem, suffix = target.name, ""
    i = 2
    while True:
        cand = target.with_name(f"{stem} {i}{suffix}")
        if not os.path.lexists(cand):
            return cand
        i += 1


def _log(entry: dict) -> dict:
    entry = {"id": uuid.uuid4().hex[:12], "ts": time.strftime("%Y-%m-%d %H:%M:%S"), **entry}
    with open(config.actions_log_path(), "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def move(src, dest_dir, cfg: dict | None = None, dry_run: bool = False, note: str = "") -> dict:
    cfg = cfg or config.load_config()
    src = _check_source(Path(src), cfg)
    dest_dir = Path(os.path.abspath(os.path.expanduser(str(dest_dir))))
    if not str(os.path.realpath(dest_dir)).startswith(str(os.path.realpath(config.home())) + os.sep):
        raise ActionError(f"Destination {dest_dir} is outside your home folder")
    if os.path.realpath(dest_dir) == os.path.realpath(src.parent):
        raise ActionError(f"{src.name} is already in {dest_dir}")
    if (os.path.realpath(dest_dir) + os.sep).startswith(os.path.realpath(src) + os.sep):
        raise ActionError("Can't move a folder into itself")
    target = _unique(dest_dir / src.name)
    if dry_run:
        return {"op": "move", "src": str(src), "dst": str(target), "dry_run": True}
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(target))
    return _log({"op": "move", "src": str(src), "dst": str(target), "note": note})


def trash(src, cfg: dict | None = None, dry_run: bool = False, note: str = "") -> dict:
    cfg = cfg or config.load_config()
    src = _check_source(Path(src), cfg)
    trash_dir = config.home() / ".Trash"
    target = _unique(trash_dir / src.name)
    if dry_run:
        return {"op": "trash", "src": str(src), "dst": str(target), "dry_run": True}
    trash_dir.mkdir(exist_ok=True)
    shutil.move(str(src), str(target))
    return _log({"op": "trash", "src": str(src), "dst": str(target), "note": note})


def history(limit: int = 500) -> list:
    p = config.actions_log_path()
    if not p.exists():
        return []
    entries = []
    undone = set()
    for line in p.read_text().splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("op") == "undo":
            undone.add(e.get("undoes"))
        entries.append(e)
    out = [dict(e, undone=e["id"] in undone) for e in entries if e.get("op") != "undo"]
    return list(reversed(out))[:limit]


def undo(action_id: str) -> dict:
    entry = next((e for e in history(100000) if e["id"] == action_id), None)
    if not entry:
        raise ActionError("No such action")
    if entry["undone"]:
        raise ActionError("Already undone")
    src, dst = entry["src"], entry["dst"]
    if not os.path.lexists(dst):
        raise ActionError(f"{dst} isn't there any more (Trash emptied, or moved again?)")
    if os.path.lexists(src):
        raise ActionError(f"Something already exists at {src}")
    os.makedirs(os.path.dirname(src), exist_ok=True)
    shutil.move(dst, src)
    return _log({"op": "undo", "undoes": action_id, "src": dst, "dst": src})


def apply(items: list, cfg: dict | None = None, dry_run: bool = False) -> list:
    """items: [{'path', 'action': 'move'|'trash', 'dest'?}] -> per-item results."""
    cfg = cfg or config.load_config()
    results = []
    for it in items:
        try:
            if it.get("action") == "trash":
                r = trash(it["path"], cfg, dry_run, it.get("note", ""))
            elif it.get("action") == "move":
                if not it.get("dest"):
                    raise ActionError("No destination chosen")
                r = move(it["path"], config.expand(it["dest"], cfg), cfg, dry_run, it.get("note", ""))
            else:
                raise ActionError(f"Unknown action {it.get('action')!r}")
            results.append({"ok": True, "path": it["path"], **r})
        except (ActionError, OSError, KeyError) as e:
            results.append({"ok": False, "path": it.get("path"), "error": str(e)})
    return results
