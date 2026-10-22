"""File operations. Nothing is ever deleted outright.

"trash" moves the item into ~/.Trash (so emptying the Trash stays your call),
"move" never overwrites (a " 2" suffix is added on name clashes), and every
operation is appended to actions.jsonl so it can be undone from the dashboard.

Several changes made together form a batch: logged with its planned items,
undone as one, and finished or put back if it was interrupted. Before each
move, journal.jsonl notes what's about to happen, so a move the app didn't get
to log (it quit, or the Mac stopped) is still found and logged next time.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from . import config, safety

_lock = threading.RLock()


class ActionError(Exception):
    pass


def _check_source(src: Path, cfg: dict) -> Path:
    src = Path(os.path.abspath(os.path.expanduser(str(src))))
    if not os.path.lexists(src):
        raise ActionError(f"{src} no longer exists")
    # A symlink is judged by where it sits, not where it points.
    real = os.path.realpath(src) if not src.is_symlink() else os.path.join(os.path.realpath(src.parent), src.name)
    if not real.startswith(str(os.path.realpath(config.home())) + os.sep):
        raise ActionError(f"{src} is outside your home folder; Mac Cleaner only touches your own files")
    reason = safety.protected_reason(str(src), cfg)
    if reason:
        raise ActionError(f"{src.name} {reason}, so Mac Cleaner won't move or trash it")
    return src


def _check_now(src: Path, dest_dir: Path, cfg: dict) -> None:
    problem = safety.premove_problem(str(src), str(dest_dir), cfg)
    if problem:
        raise ActionError(problem)


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


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _append(path: Path, entry: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _log(entry: dict) -> dict:
    entry = {"id": _new_id(), "ts": time.strftime("%Y-%m-%d %H:%M:%S"), **entry}
    _append(config.actions_log_path(), entry)
    return entry


def _journal_path() -> Path:
    return config.app_dir() / "journal.jsonl"


def _journaled(entry: dict, work) -> dict:
    """Note the change, do it, log it, then mark the note done."""
    entry = {"id": _new_id(), "ts": time.strftime("%Y-%m-%d %H:%M:%S"), **entry}
    with _lock:
        _append(_journal_path(), {"pending": entry})
        moved = work()
        if moved is not None:
            entry = dict(entry, items=moved)
        _append(config.actions_log_path(), entry)
        _append(_journal_path(), {"done": entry["id"]})
    return entry


def recover() -> list:
    """Log any change that happened but wasn't logged (the app stopped in between)."""
    with _lock:
        p = _journal_path()
        if not p.exists():
            return []
        pending, done = {}, set()
        for line in p.read_text().splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if "pending" in rec:
                pending[rec["pending"]["id"]] = rec["pending"]
            elif "done" in rec:
                done.add(rec["done"])
        logged = {e.get("id") for e in _read_log()}
        recovered = []
        for aid, e in pending.items():
            if aid in done or aid in logged:
                continue
            note = ((e.get("note") or "") + " (finished after an interruption)").strip()
            if e.get("items"):
                items = [[s, d] for s, d in e["items"] if os.path.lexists(d) and not os.path.lexists(s)]
                if items:
                    recovered.append(_log(dict(e, items=items, note=note)))
            elif os.path.lexists(e["dst"]) and not os.path.lexists(e["src"]):
                recovered.append(_log(dict(e, note=note)))
        p.unlink()
        return recovered


def move(src, dest_dir, cfg: dict | None = None, dry_run: bool = False, note: str = "",
         batch: str | None = None) -> dict:
    cfg = cfg or config.load_config()
    src = _check_source(Path(src), cfg)
    dest_dir = Path(os.path.abspath(os.path.expanduser(str(dest_dir))))
    if not str(os.path.realpath(dest_dir)).startswith(str(os.path.realpath(config.home())) + os.sep):
        raise ActionError(f"Destination {dest_dir} is outside your home folder")
    if os.path.realpath(dest_dir) == os.path.realpath(src.parent):
        raise ActionError(f"{src.name} is already in {dest_dir}")
    if (os.path.realpath(dest_dir) + os.sep).startswith(os.path.realpath(src) + os.sep):
        raise ActionError("Can't move a folder into itself")
    _check_now(src, dest_dir, cfg)
    problem = safety.project_move_problem(str(src))  # not on undo: putting things back always works
    if problem:
        raise ActionError(problem)
    target = _unique(dest_dir / src.name)
    if dry_run:
        return {"op": "move", "src": str(src), "dst": str(target), "dry_run": True}

    def work():
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))

    entry = _journaled({"op": "move", "src": str(src), "dst": str(target), "note": note, "batch": batch}, work)
    from . import marks
    marks.moved(str(src), str(target))
    return entry


def trash(src, cfg: dict | None = None, dry_run: bool = False, note: str = "", batch: str | None = None) -> dict:
    cfg = cfg or config.load_config()
    src = _check_source(Path(src), cfg)
    trash_dir = config.home() / ".Trash"
    _check_now(src, trash_dir, cfg)
    target = _unique(trash_dir / src.name)
    if dry_run:
        return {"op": "trash", "src": str(src), "dst": str(target), "dry_run": True}

    def work():
        trash_dir.mkdir(exist_ok=True)
        shutil.move(str(src), str(target))

    return _journaled({"op": "trash", "src": str(src), "dst": str(target), "note": note, "batch": batch}, work)


def trash_group(paths: list, label: str, cfg: dict | None = None, batch: str | None = None) -> dict:
    """Trash several files into one (visible) folder in the Trash, logged and
    undone as a single action."""
    cfg = cfg or config.load_config()
    srcs = [_check_source(Path(p), cfg) for p in paths]
    trash_dir = config.home() / ".Trash"
    for s in srcs:
        _check_now(s, trash_dir, cfg)
    folder = _unique(trash_dir / label)
    plan = []
    taken = set()
    for src in srcs:
        dst = folder / src.name
        i = 2
        while str(dst) in taken:
            dst = folder / f"{Path(src.name).stem} {i}{Path(src.name).suffix}"
            i += 1
        taken.add(str(dst))
        plan.append([str(src), str(dst)])
    errors = []

    def work():
        folder.mkdir(parents=True)
        moved = []
        for s, d in plan:
            try:
                shutil.move(s, d)
                moved.append([s, d])
            except OSError as e:
                errors.append(e)
                break
        if not moved:
            folder.rmdir()
            raise ActionError(f"Nothing was moved: {errors[0] if errors else 'unknown error'}")
        return moved

    entry = _journaled({"op": "trash", "src": os.path.dirname(plan[0][0]) if plan else "", "dst": str(folder),
                        "items": plan, "note": f"{len(plan)} files", "batch": batch}, work)
    if errors:
        entry = dict(entry, partial=f"{len(entry['items'])} of {len(srcs)} moved before an error: {errors[0]}")
    return entry


# --- history and undo ---------------------------------------------------------
def _read_log() -> list:
    p = config.actions_log_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def history(limit: int = 500) -> list:
    """Moves and trashes, newest first."""
    recover()
    entries = _read_log()
    undone = {e.get("undoes") for e in entries if e.get("op") == "undo"}
    out = [dict(e, undone=e["id"] in undone) for e in entries if e.get("op") in ("move", "trash")]
    return list(reversed(out))[:limit]


def batches(limit: int = 200) -> list:
    """Each batch with how far it got: planned, done, undone, and whether it finished."""
    entries = _read_log()
    undone = {e.get("undoes") for e in entries if e.get("op") == "undo"}
    by_id = {}
    for e in entries:
        if e.get("op") == "batch":
            by_id[e["id"]] = {"id": e["id"], "ts": e["ts"], "label": e.get("label", ""),
                              "planned": len(e.get("items") or []) or e.get("planned", 0),
                              "done": 0, "undone": 0, "finished": False, "ended_done": None}
        elif e.get("op") == "batch-end" and e.get("batch") in by_id:
            by_id[e["batch"]].update(finished=True, ended_done=e.get("done"))
        elif e.get("op") in ("move", "trash") and e.get("batch") in by_id:
            b = by_id[e["batch"]]
            b["done"] += 1
            if e["id"] in undone:
                b["undone"] += 1
    return list(reversed(list(by_id.values())))[:limit]


def interrupted_batches() -> list:
    return [b for b in batches(1000) if not b["finished"] and b["done"] > b["undone"]]


def undo(action_id: str) -> dict:
    entry = next((e for e in history(100000) if e["id"] == action_id), None)
    if not entry:
        raise ActionError("No such action")
    if entry["undone"]:
        raise ActionError("Already undone")
    cfg = config.load_config()
    if entry.get("items"):  # a group: put every file back, then drop the folder in the Trash
        missing = [d for _, d in entry["items"] if not os.path.lexists(d)]
        if missing:
            raise ActionError(f"{len(missing)} of these files aren't in the Trash any more")
        clash = [s for s, _ in entry["items"] if os.path.lexists(s)]
        if clash:
            raise ActionError(f"Something already exists at {clash[0]}")
        for s_, d in entry["items"]:
            _check_now(Path(d), Path(os.path.dirname(s_)), cfg)
        with _lock:
            for s_, d in entry["items"]:
                os.makedirs(os.path.dirname(s_), exist_ok=True)
                shutil.move(d, s_)
            try:
                os.rmdir(entry["dst"])
            except OSError:
                pass
            return _log({"op": "undo", "undoes": action_id, "src": entry["dst"], "dst": entry["src"]})
    src, dst = entry["src"], entry["dst"]
    if not os.path.lexists(dst):
        raise ActionError(f"{dst} isn't there any more (Trash emptied, or moved again?)")
    if os.path.lexists(src):
        raise ActionError(f"Something already exists at {src}")
    _check_now(Path(dst), Path(os.path.dirname(src)), cfg)
    with _lock:
        os.makedirs(os.path.dirname(src), exist_ok=True)
        shutil.move(dst, src)
        logged = _log({"op": "undo", "undoes": action_id, "src": dst, "dst": src})
    from . import marks
    marks.moved(dst, src)
    return logged


def undo_batch(batch_id: str) -> dict:
    """Put back everything a batch changed, newest first. Items that can't be put
    back (moved again by hand, Trash emptied) are skipped and named."""
    todo = [e for e in history(100000) if e.get("batch") == batch_id and not e["undone"]]
    if not todo and not any(b["id"] == batch_id for b in batches(100000)):
        raise ActionError("No such batch")
    undone, failed = 0, []
    for e in todo:
        try:
            undo(e["id"])
            undone += 1
        except (ActionError, OSError) as err:
            failed.append({"path": e["src"], "error": str(err)})
    return {"undone": undone, "failed": failed}


# --- applying a list of changes -----------------------------------------------
def _one(it: dict, cfg: dict, dry_run: bool, batch: str | None) -> dict:
    if it.get("action") == "trash":
        return trash(it["path"], cfg, dry_run, it.get("note", ""), batch)
    if it.get("action") == "move":
        if not it.get("dest"):
            raise ActionError("No destination chosen")
        return move(it["path"], config.expand(it["dest"], cfg), cfg, dry_run, it.get("note", ""), batch)
    raise ActionError(f"Unknown action {it.get('action')!r}")


def apply(items: list, cfg: dict | None = None, dry_run: bool = False, label: str = "") -> list:
    """items: [{'path', 'action': 'move'|'trash', 'dest'?}] -> per-item results.
    A real run is one batch, so it can be undone as one."""
    cfg = cfg or config.load_config()
    batch = None
    if not dry_run and items:
        planned = [{"path": it.get("path"), "action": it.get("action"),
                    "dest": str(config.expand(it["dest"], cfg)) if it.get("dest") else None,
                    "note": it.get("note", "")} for it in items]
        batch = _log({"op": "batch", "label": label or f"{len(items)} item{'s' if len(items) != 1 else ''}",
                      "items": planned})["id"]
    results = []
    try:
        for it in items:
            try:
                r = _one(it, cfg, dry_run, batch)
                results.append({"ok": True, "path": it["path"], **r})
            except (ActionError, OSError, KeyError) as e:
                results.append({"ok": False, "path": it.get("path"), "error": str(e)})
    finally:
        if batch:
            _log({"op": "batch-end", "batch": batch, "done": sum(1 for r in results if r["ok"])})
    if batch:
        for r in results:
            r["batch"] = batch
    return results


def resume_batch(batch_id: str, cfg: dict | None = None) -> list:
    """Finish an interrupted batch: do the planned items that weren't done."""
    cfg = cfg or config.load_config()
    start = next((e for e in _read_log() if e.get("op") == "batch" and e["id"] == batch_id), None)
    if not start:
        raise ActionError("No such batch")
    done = {e["src"] for e in _read_log() if e.get("batch") == batch_id and e.get("op") in ("move", "trash")}
    todo = [it for it in start.get("items") or [] if it["path"] not in done]
    results = []
    for it in todo:
        try:
            results.append({"ok": True, "path": it["path"], **_one(it, cfg, False, batch_id)})
        except (ActionError, OSError, KeyError) as e:
            results.append({"ok": False, "path": it.get("path"), "error": str(e)})
    _log({"op": "batch-end", "batch": batch_id, "done": len(done) + sum(1 for r in results if r["ok"])})
    return results
