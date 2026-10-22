"""Walk the disk and record sizes into a fresh SQLite snapshot.

Sizes are recorded twice: `size` is the logical length, `alloc` is what the
file actually occupies on disk (st_blocks). They differ for sparse files and,
importantly, for iCloud files that have been "optimised" away to the cloud:
those still report their full size but take ~0 bytes locally (`dataless`).
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import threading
import time
from pathlib import Path

from . import ableton, classify, config, db, dupes

SF_DATALESS = 0x40000000  # macOS: file contents live only in iCloud

_PACKAGE_CATEGORY = {
    ".app": "app", ".bundle": "app", ".framework": "app", ".plugin": "app", ".kext": "app",
    ".vst": "plugin", ".vst3": "plugin", ".component": "plugin", ".aaxplugin": "plugin", ".clap": "plugin",
    ".photoslibrary": "image", ".lrlibrary": "image", ".lrdata": "image", ".sketch": "image",
    ".musiclibrary": "audio", ".logicx": "audio", ".band": "audio",
    ".fcpbundle": "video", ".imovielibrary": "video", ".tvlibrary": "video", ".prproj": "video",
    ".pages": "document", ".numbers": "document", ".key": "document", ".rtfd": "document",
    ".xcodeproj": "code", ".xcworkspace": "code", ".playground": "code", ".xcarchive": "code",
}
_SYSTEM_ROOTS = {"/System", "/usr", "/bin", "/sbin", "/private", "/Library", "/opt", "/cores"}
# Sets, presets/racks (checked for what they load) and .asd files are always recorded.
# Audio and Max devices are recorded whatever their size, so missing samples can be found by name.
_ALWAYS_STORE_EXT = {".als", ".asd", ".adg", ".adv", ".alc", ".agr", ".amxd",
                     ".wav", ".wave", ".aif", ".aiff", ".aifc", ".flac", ".mp3", ".m4a", ".ogg", ".caf"}
INDEX_VERSION = 4  # 2: presets and racks in the "used by" index; 3: track names; 4: every audio file


class ScanCancelled(Exception):
    pass


class Scanner:
    def __init__(self, cfg: dict | None = None, roots: list | None = None, progress=None):
        self.cfg = cfg or config.load_config()
        self.roots = [str(config.expand(r, self.cfg)) for r in (roots or self.cfg["scan_roots"])]
        self.exclude = {str(config.expand(p, self.cfg)) for p in self.cfg.get("exclude", [])}
        self.exclude.add(str(config.app_dir()))
        self.inboxes = {str(p) for p in config.inbox_paths(self.cfg)}
        self.min_size = int(float(self.cfg.get("min_file_mb", 1)) * 1_000_000)
        h = str(config.home())
        self.library = os.path.join(h, "Library")
        self.user_zones = {os.path.join(h, config.ICLOUD_REL), os.path.join(h, "Library", "CloudStorage")}
        self.trash = os.path.join(h, ".Trash")
        self.progress = progress
        self.cancel = threading.Event()
        self.state = {"phase": "idle", "files": 0, "bytes": 0, "current": "", "errors": 0}
        self._seen_inodes = set()
        self._dir_rows, self._file_rows = [], []
        self._cats = {}

    # -- public -------------------------------------------------------------
    def run(self) -> Path:
        final = config.db_path()
        tmp = final.with_name("scan-tmp.db")
        if tmp.exists():
            tmp.unlink()
        self.con = db.connect(tmp)
        started = time.time()
        sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
        try:
            self._set("walking")
            totals = [0, 0, 0]
            for root in self.roots:
                if not os.path.isdir(root):
                    continue
                s, a, n, _ = self._walk(root, 0, self._zone_for(root, "user"), None, False)
                totals[0] += s
                totals[1] += a
                totals[2] += n
            self._flush(force=True)
            self.con.executemany(
                "INSERT INTO cat_stats VALUES (?,?,?,?,?)",
                [(c, e, v[0], v[1], v[2]) for (c, e), v in self._cats.items()])
            self.con.commit()

            self._set("finding duplicates")
            dupes.find_duplicates(self.con, self.cfg, cancel=self.cancel, state=self.state)
            self._set("reading Ableton sets")
            ableton.analyse_sets(self.con, self.cfg, cancel=self.cancel, state=self.state)

            du = shutil.disk_usage("/")
            meta = {
                "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "duration_s": round(time.time() - started, 1),
                "roots": json.dumps(self.roots),
                "total_size": totals[0], "total_alloc": totals[1], "total_files": totals[2],
                "disk_total": du.total, "disk_used": du.used, "disk_free": du.free,
                "errors": self.state["errors"],
                "home": str(config.home()), "index_version": INDEX_VERSION,
            }
            self.con.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)",
                                 [(k, str(v)) for k, v in meta.items()])
            self.con.commit()
            self.con.close()
            os.replace(tmp, final)
            self._set("done")
            return final
        except BaseException:
            self.con.close()
            if tmp.exists():
                tmp.unlink()
            self._set("cancelled" if self.cancel.is_set() else "failed")
            raise

    # -- internals ----------------------------------------------------------
    def _set(self, phase: str) -> None:
        self.state["phase"] = phase
        if self.progress:
            self.progress(dict(self.state))

    def _zone_for(self, path: str, parent_zone: str) -> str:
        if path in self.user_zones:
            return "user"
        if path == self.library:
            return "library"
        if path in _SYSTEM_ROOTS:
            return "system"
        return parent_zone

    def _walk(self, path: str, depth: int, zone: str, pkg_cat, in_inbox: bool):
        """Returns (size, alloc, files, newest mtime) for `path`, recording rows."""
        if self.cancel.is_set():
            raise ScanCancelled()
        size = alloc = nfiles = 0
        newest = 0.0
        kind = "dir"
        own_pkg = None
        if pkg_cat is None:
            suffix = os.path.splitext(path)[1].lower()
            if suffix in classify.PACKAGE_SUFFIXES:
                own_pkg = _PACKAGE_CATEGORY.get(suffix, "other")
                kind = "package"
        inner_pkg = pkg_cat or own_pkg
        in_inbox = in_inbox or path in self.inboxes
        try:
            it = os.scandir(path)
        except OSError as e:
            self.state["errors"] += 1
            if self.state["errors"] <= 2000:
                self.con.execute("INSERT INTO errors VALUES (?,?)", (path, e.strerror or str(e)))
            return 0, 0, 0, 0.0
        with it:
            for entry in it:
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                mode = st.st_mode
                if stat.S_ISDIR(mode):
                    if entry.path in self.exclude:
                        continue
                    if entry.name == "Ableton Project Info" \
                            and os.path.basename(path).casefold() != classify.USER_LIBRARY_NAME:
                        kind = "ableton-project" if kind == "dir" else kind
                    child_zone = zone if inner_pkg else self._zone_for(entry.path, zone)
                    s, a, n, m = self._walk(entry.path, depth + 1, child_zone, inner_pkg, in_inbox)
                    size += s
                    alloc += a
                    nfiles += n
                    newest = max(newest, m)
                elif stat.S_ISREG(mode):
                    if st.st_nlink > 1:
                        key = (st.st_dev, st.st_ino)
                        if key in self._seen_inodes:
                            continue
                        self._seen_inodes.add(key)
                    fsize = st.st_size
                    falloc = st.st_blocks * 512 if hasattr(st, "st_blocks") else fsize
                    flags = getattr(st, "st_flags", 0)
                    name = entry.name
                    dataless = bool(flags & SF_DATALESS) or (name.startswith(".") and name.endswith(".icloud"))
                    ext = os.path.splitext(name)[1].lower()
                    if len(ext) > 12:
                        ext = ""
                    if inner_pkg:
                        cat = inner_pkg
                    elif zone != "user":
                        cat = zone
                    else:
                        cat = classify.EXT_CATEGORY.get(ext, "other")
                    key = (cat, ext if not inner_pkg else os.path.splitext(path)[1].lower())
                    c = self._cats.setdefault(key, [0, 0, 0])
                    c[0] += 1
                    c[1] += fsize
                    c[2] += falloc
                    size += fsize
                    alloc += falloc
                    nfiles += 1
                    newest = max(newest, st.st_mtime)
                    if not inner_pkg and (fsize >= self.min_size or in_inbox or ext in _ALWAYS_STORE_EXT
                                          or (ext in classify.PARTIAL_DOWNLOAD_EXTS)):
                        self._file_rows.append((
                            entry.path, path, name, ext, cat, fsize, falloc, st.st_mtime,
                            getattr(st, "st_birthtime", st.st_mtime), int(dataless)))
                    self.state["files"] += 1
                    self.state["bytes"] += falloc
                    if self.state["files"] % 5000 == 0:
                        self.state["current"] = path
                        if self.progress:
                            self.progress(dict(self.state))
        if not pkg_cat:  # don't record the insides of packages
            try:
                mtime = os.stat(path, follow_symlinks=False).st_mtime
            except OSError:
                mtime = newest
            self._dir_rows.append((path, os.path.dirname(path), os.path.basename(path) or path,
                                   depth, size, alloc, nfiles, mtime, kind, zone))
            self._flush()
        return size, alloc, nfiles, newest

    def _flush(self, force: bool = False) -> None:
        if force or len(self._dir_rows) + len(self._file_rows) > 5000:
            self.con.executemany("INSERT OR REPLACE INTO dirs VALUES (?,?,?,?,?,?,?,?,?,?)", self._dir_rows)
            self.con.executemany("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?,?,?)", self._file_rows)
            self._dir_rows.clear()
            self._file_rows.clear()


class BackgroundScan:
    """One scan at a time, run on a thread so the dashboard stays responsive."""

    def __init__(self):
        self.scanner = None
        self.thread = None
        self.error = None

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, cfg: dict, roots: list | None = None) -> bool:
        if self.running:
            return False
        self.error = None
        self.scanner = Scanner(cfg, roots)

        def target():
            try:
                self.scanner.run()
            except ScanCancelled:
                self.error = "cancelled"
            except Exception as e:  # surfaced in the dashboard
                self.error = f"{type(e).__name__}: {e}"

        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()
        return True

    def status(self) -> dict:
        if not self.scanner:
            return {"running": False, "phase": "idle"}
        return {"running": self.running, "error": self.error, "roots": self.scanner.roots,
                **self.scanner.state}

    def cancel(self) -> None:
        if self.scanner:
            self.scanner.cancel.set()
