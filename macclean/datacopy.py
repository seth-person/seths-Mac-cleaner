"""A copy of Mac Cleaner's own data (tags, marks, saved plans and settings)
kept in your library folder, so it goes wherever your files go. A new Mac, or
Mac Cleaner installed again, can pick it up.

  mirror   after each change the files are copied to
           <library>/Mac Cleaner data/ (only once the library is set up)
  restore  when this Mac has no tags or marks yet and a copy is found, the
           dashboard offers to bring it back. Paths under the old home folder
           are rewritten to this one, and what was here is kept aside first.

The undo history and the scan stay on this Mac: they describe this Mac's disk.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path

from . import __version__, config

FOLDER = "Mac Cleaner data"
FILES = ("marks.json", "plans.json", "config.json")
ABOUT = "about.json"
README = """This folder is Mac Cleaner's own data: your project tags and marks
(marks.json), saved plans (plans.json) and settings (config.json).

Mac Cleaner keeps it up to date by itself, so it travels with your files.
If you set Mac Cleaner up on another Mac, it offers to bring this back.
It's safe to leave alone. Deleting it only removes this copy.
"""

_written = {}
_lock = threading.Lock()


def folder(cfg: dict) -> Path | None:
    """Where the copy goes, or None until the library is set up."""
    if not cfg.get("library_ready"):
        return None
    return Path(config.library_paths(cfg)["root"]) / FOLDER


def mirror(cfg: dict | None = None) -> str | None:
    """Copy whatever changed since the last time. Returns the folder, if any."""
    cfg = cfg or config.load_config()
    d = folder(cfg)
    if d is None or not d.parent.is_dir():
        return None
    with _lock:
        changed = False
        for name in FILES:
            try:
                data = (config.app_dir() / name).read_bytes()
            except OSError:
                continue
            if _written.get((str(d), name)) == data:
                continue
            d.mkdir(exist_ok=True)
            tmp = d / (name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, d / name)
            _written[(str(d), name)] = data
            changed = True
        if changed:
            (d / ABOUT).write_text(json.dumps({"format": 1, "home": str(config.home()), "saved_at": time.time(),
                                               "version": __version__}, indent=2))
            if not (d / "README.txt").exists():
                (d / "README.txt").write_text(README)
    return str(d)


def mirror_soon() -> None:
    """mirror() without holding up the reply (after a change in the dashboard)."""
    def run():
        try:
            mirror()
        except Exception:  # a full or offline iCloud must never break the dashboard
            pass
    threading.Thread(target=run, daemon=True).start()


# --- bringing it back ----------------------------------------------------------
def _has_data() -> bool:
    try:
        m = json.loads((config.app_dir() / "marks.json").read_text())
    except (OSError, ValueError):
        return False
    return any(m.get(k) for k in ("important", "tags", "flags", "tag_defs"))


def _candidates(cfg: dict) -> list:
    out = []
    d = folder(cfg)
    if d:
        out.append(d)
    cloud = config.expand(cfg.get("cloud_root") or config.DEFAULT_CONFIG["cloud_root"], cfg)
    out.append(cloud / FOLDER)
    try:  # a library one level inside iCloud Drive, like iCloud Drive/Active Storage
        out += [e / FOLDER for e in sorted(cloud.iterdir()) if e.is_dir() and not e.name.startswith(".")]
    except OSError:
        pass
    return out


def offer(cfg: dict | None = None) -> dict | None:
    """A copy worth restoring, when this Mac has no tags or marks of its own."""
    cfg = cfg or config.load_config()
    if _has_data():
        return None
    for d in _candidates(cfg):
        try:
            about = json.loads((d / ABOUT).read_text())
            marks = json.loads((d / "marks.json").read_text())
        except (OSError, ValueError):
            continue
        tagged = sum(1 for t in (marks.get("tags") or {}).values() if isinstance(t, dict) and t.get("tags"))
        return {"path": str(d), "saved_at": about.get("saved_at"), "home": about.get("home"),
                "tagged": tagged, "important": len(marks.get("important") or {}),
                "tags": len(marks.get("tag_defs") or []), "files": [n for n in FILES if (d / n).exists()]}
    return None


def _rehome(value, old: str, new: str):
    if isinstance(value, str):
        return new + value[len(old):] if value == old or value.startswith(old + "/") else value
    if isinstance(value, list):
        return [_rehome(v, old, new) for v in value]
    if isinstance(value, dict):
        return {_rehome(k, old, new): _rehome(v, old, new) for k, v in value.items()}
    return value


def restore(path: str) -> dict:
    """Bring back a copy found by offer(). What was here is kept in before-restore-<time>/."""
    d = Path(path)
    if d.name != FOLDER or not (d / ABOUT).exists():
        raise ValueError("That isn't a Mac Cleaner data folder")
    about = json.loads((d / ABOUT).read_text())
    old, new = about.get("home") or "", str(config.home())
    aside = config.app_dir() / time.strftime("before-restore-%Y%m%d-%H%M%S")
    restored = []
    for name in FILES:
        try:
            data = json.loads((d / name).read_text())
        except (OSError, ValueError):
            continue
        if old and old != new:
            data = _rehome(data, old, new)
        here = config.app_dir() / name
        if here.exists():
            aside.mkdir(parents=True, exist_ok=True)
            shutil.copy2(here, aside / name)
        tmp = here.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, here)
        restored.append(name)
    return {"restored": restored, "kept_aside": str(aside) if aside.exists() else None}
