"""Files other apps keep track of by location, so moving them would break that app.

  rekordbox    its database is encrypted, so Mac Cleaner reads the collection
               you export from rekordbox (File → Export Collection in xml
               format). Every track in it stays where it is.
  Final Cut    a library that leaves media in place keeps links (symlinks)
               to it inside the library. Those files stay where they are.

Read-only. Both lists feed the same "used by" protection as Ableton sets.
"""
from __future__ import annotations

import os
import time
from urllib.parse import unquote, urlparse
from xml.etree.ElementTree import iterparse

from . import config, db

FCP_WALK_LIMIT = 100_000
STALE_DAYS = 30

_cache = {}


def rekordbox_tracks(xml_path: str) -> list:
    """Track file paths from a rekordbox collection export."""
    out = []
    for _, el in iterparse(xml_path, events=("end",)):
        if el.tag == "TRACK":
            loc = el.get("Location")
            if loc:
                u = urlparse(loc)
                path = unquote(u.path) if u.scheme == "file" else unquote(loc)
                if path.startswith("/"):
                    out.append(os.path.normpath(path))
            el.clear()
        elif el.tag == "PLAYLISTS":
            el.clear()
    return out


def rekordbox_status(cfg: dict) -> dict:
    path = str(config.expand(cfg.get("rekordbox_xml") or "", cfg)) if cfg.get("rekordbox_xml") else ""
    if not path:
        return {"set": False}
    try:
        st = os.stat(path)
    except OSError:
        return {"set": True, "path": path, "error": "That file isn't there any more. Export the collection again."}
    key = ("rb", path, st.st_mtime)
    hit = _cache.get(key)
    if hit is None:
        try:
            tracks = rekordbox_tracks(path)
            hit = {"tracks": tracks}
        except Exception as e:  # not a rekordbox export, or a broken one
            hit = {"tracks": [], "error": f"That doesn't look like a rekordbox collection export ({e})"}
        _cache.clear() if len(_cache) > 8 else None
        _cache[key] = hit
    days = (time.time() - st.st_mtime) / 86400
    return {"set": True, "path": path, "tracks": len(hit["tracks"]), "exported_days": days,
            "stale": days > STALE_DAYS, "error": hit.get("error"), "_paths": hit["tracks"]}


def fcp_links(con) -> dict:
    """norm-free {target path: library name} for media Final Cut libraries link to."""
    if con is None:
        return {}
    key = ("fcp", tuple(sorted(db.meta(con).items())))
    if key in _cache:
        return _cache[key]
    home = os.path.realpath(config.home())
    out = {}
    libs = [r["path"] for r in con.execute("SELECT path FROM dirs WHERE name LIKE '%.fcpbundle'")]
    for lib in libs:
        n = 0
        name = os.path.basename(lib)
        for dirpath, dirnames, filenames in os.walk(lib):
            for f in filenames + dirnames:
                p = os.path.join(dirpath, f)
                n += 1
                if not os.path.islink(p):
                    continue
                target = os.readlink(p)
                if not os.path.isabs(target):
                    target = os.path.normpath(os.path.join(dirpath, target))
                if (os.path.realpath(target) + os.sep).startswith(home + os.sep) and not target.startswith(lib + os.sep):
                    out[target] = name
            if n > FCP_WALK_LIMIT:
                break
    _cache[key] = out
    return out


def protected(con, cfg: dict | None = None) -> dict:
    """{path: who uses it} for everything other apps keep track of."""
    cfg = cfg or config.load_config()
    out = {}
    rb = rekordbox_status(cfg)
    for p in rb.get("_paths") or []:
        out[p] = "rekordbox"
    for p, lib in fcp_links(con).items():
        out.setdefault(p, f"the Final Cut library “{lib[:-len('.fcpbundle')] if lib.endswith('.fcpbundle') else lib}”")
    return out


def status(con, cfg: dict) -> dict:
    rb = rekordbox_status(cfg)
    rb.pop("_paths", None)
    fcp = fcp_links(con)
    libs = sorted(set(fcp.values()))
    return {"rekordbox": rb, "final_cut": {"links": len(fcp), "libraries": len(libs),
                                           "library_names": [l[:-len(".fcpbundle")] for l in libs][:20]}}
