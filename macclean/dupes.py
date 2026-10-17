"""Find duplicate files among the user's own big files.

Candidates are grouped by size, then by a hash of the first and last 64 KB,
and only then fully hashed, so most files are never read in full. Files that
only exist in iCloud are skipped (reading them would download them), as are
files inside Ableton projects: "Collect All and Save" deliberately copies
samples into every project, and removing those copies would break the sets.
"""
from __future__ import annotations

import hashlib
import os
from collections import defaultdict

from . import config

CHUNK = 64 * 1024
MIN_DUPE_SIZE = 1_000_000


def _partial_hash(path: str, size: int) -> str | None:
    try:
        with open(path, "rb") as f:
            h = hashlib.blake2b(f.read(CHUNK), digest_size=16)
            if size > 2 * CHUNK:
                f.seek(-CHUNK, os.SEEK_END)
                h.update(f.read(CHUNK))
        return h.hexdigest()
    except OSError:
        return None


def _full_hash(path: str, cancel=None) -> str | None:
    h = hashlib.blake2b(digest_size=20)
    try:
        with open(path, "rb") as f:
            while True:
                if cancel is not None and cancel.is_set():
                    return None
                block = f.read(1 << 20)
                if not block:
                    break
                h.update(block)
        return h.hexdigest()
    except OSError:
        return None


def _excluded(path: str, project_dirs: list, library: str) -> bool:
    if path.startswith(library + os.sep) and config.ICLOUD_REL not in path and "/CloudStorage/" not in path:
        return True
    if "/." in path:  # hidden folders: app state, .git, .Trash
        return True
    return any(path.startswith(p + os.sep) for p in project_dirs)


def find_duplicates(con, cfg, cancel=None, state=None) -> int:
    library = os.path.join(str(config.home()), "Library")
    project_dirs = [r["path"] for r in con.execute("SELECT path FROM dirs WHERE kind='ableton-project'")]
    by_size = defaultdict(list)
    for r in con.execute(
            "SELECT path, size FROM files WHERE dataless=0 AND size>=? AND size IN "
            "(SELECT size FROM files WHERE dataless=0 AND size>=? GROUP BY size HAVING COUNT(*)>1)",
            (MIN_DUPE_SIZE, MIN_DUPE_SIZE)):
        if not _excluded(r["path"], project_dirs, library):
            by_size[r["size"]].append(r["path"])

    group_id = 0
    rows = []
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_partial = defaultdict(list)
        for p in paths:
            ph = _partial_hash(p, size)
            if ph:
                by_partial[ph].append(p)
        for same in by_partial.values():
            if len(same) < 2:
                continue
            by_full = defaultdict(list)
            for p in same:
                if cancel is not None and cancel.is_set():
                    return group_id
                fh = _full_hash(p, cancel)
                if fh:
                    by_full[fh].append(p)
            for fh, group in by_full.items():
                if len(group) < 2:
                    continue
                group_id += 1
                rows.extend((group_id, fh, size, p) for p in group)
        if state is not None:
            state["current"] = f"{group_id} duplicate groups"
    con.executemany("INSERT INTO dupes VALUES (?,?,?,?)", rows)
    con.commit()
    return group_id
