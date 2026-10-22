"""A plain-text summary of the scan: what's where, how big, and how messy.

It's meant to be read by you, or pasted into a chat with Claude so it can
help design folder structures and rules for your actual files. It contains
folder and file *names* but never file contents.
"""
from __future__ import annotations

import os
import time

from . import ableton, config, db, inbox, purge
from .classify import human


def _short(p: str, h: str) -> str:
    return "~" + p[len(h):] if p.startswith(h) else p


def build(con, cfg: dict) -> str:
    h = str(config.home())
    m = db.meta(con)
    cloud = str(config.expand(cfg["cloud_root"], cfg))
    L = []
    w = L.append
    w("# Mac survey")
    w(f"Scanned {m.get('scanned_at', '?')} in {m.get('duration_s', '?')}s · roots: {m.get('roots')}")
    if m.get("disk_total"):
        w(f"Disk: {human(int(m['disk_used']))} used of {human(int(m['disk_total']))} "
          f"({human(int(m['disk_free']))} free). Scanned: {human(int(m['total_alloc']))} in "
          f"{int(m['total_files']):,} files. Unreadable folders: {m.get('errors', 0)}")
    w("")

    w("## What kind of stuff (on disk)")
    for r in con.execute("SELECT category, SUM(alloc) a, SUM(count) n FROM cat_stats GROUP BY category ORDER BY a DESC"):
        w(f"- {r['category']}: {human(r['a'])} ({r['n']:,} files)")
    w("")

    w("## Biggest folders in your home (2 levels)")
    for r in con.execute("SELECT * FROM dirs WHERE parent=? ORDER BY alloc DESC LIMIT 15", (h,)):
        w(f"- {_short(r['path'], h)}: {human(r['alloc'])}, {r['files']:,} files")
        for c in con.execute("SELECT * FROM dirs WHERE parent=? ORDER BY alloc DESC LIMIT 6", (r["path"],)):
            w(f"    - {c['name']}: {human(c['alloc'])}, {c['files']:,} files")
    w("")

    w("## iCloud Drive structure (3 levels)")
    root = con.execute("SELECT * FROM dirs WHERE path=?", (cloud,)).fetchone()
    if root:
        w(f"Total {human(root['size'])} logical / {human(root['alloc'])} downloaded to this Mac")

        def tree(path, depth):
            for c in con.execute("SELECT * FROM dirs WHERE parent=? ORDER BY size DESC LIMIT 25", (path,)):
                if c["name"].startswith("."):
                    continue
                tag = " [Ableton project]" if c["kind"] == "ableton-project" and c["name"].casefold() != "user library" else ""
                w("  " * depth + f"- {c['name']}/ — {human(c['size'])}, {c['files']:,} files{tag}")
                if depth < 2 and c["kind"] == "dir":
                    tree(c["path"], depth + 1)
        tree(cloud, 0)
    else:
        w("(iCloud Drive folder wasn't part of the scan)")
    w("")

    w("## Catch-all folders")
    for ib in inbox.list_inboxes(cfg)["inboxes"]:
        w(f"### {_short(ib['path'], h)}: {ib['count']} items, {human(ib['size'])}, "
          f"{ib['stale']} untouched for {cfg.get('stale_days')}+ days")
        cats = {}
        for it in ib["items"]:
            c = cats.setdefault(it["category"], [0, 0])
            c[0] += 1
            c[1] += it["size"]
        w("By type: " + ", ".join(f"{k} {v[0]} ({human(v[1])})" for k, v in sorted(cats.items(), key=lambda x: -x[1][1])))
        buckets = [0, 0, 0, 0]
        for it in ib["items"]:
            a = it["age_days"]
            buckets[0 if a < 7 else 1 if a < 30 else 2 if a < 365 else 3] += 1
        w(f"Age: <1 week {buckets[0]}, 1–4 weeks {buckets[1]}, 1–12 months {buckets[2]}, older {buckets[3]}")
        for it in ib["items"][:40]:
            s = it.get("suggestion") or {}
            sug = (s.get("action", "") + " → " + _short(s.get("dest", ""), h)) if s.get("dest") else s.get("action", "—")
            w(f"- {it['name']}{'/' if it['is_dir'] else ''} [{it['kind']}/{it['category']}] {human(it['size'])}, "
              f"{int(it['age_days'])}d — suggest: {sug}")
        if ib["count"] > 40:
            w(f"- … and {ib['count'] - 40} more")
        w("")

    w("## Ableton")
    ov = ableton.overview(con, cfg)
    t = ov["totals"]
    w(f"{t['projects']} projects, {human(t['alloc'])}; {t['outside_library']} outside {_short(ov['root'], h)}; "
      f"{t['needs_collect']} reference files outside their project or missing. "
      f"Auto-backups {human(t['backup_bytes'])}, .asd files {human(t['asd_bytes'])}.")
    w("Where projects live:")
    for loc in ov["locations"]:
        w(f"- {_short(loc['location'], h)}: {loc['count']} projects, {human(loc['alloc'])}")
    w("Projects (newest first):")
    for p in ov["projects"][:80]:
        sets = len(p["sets"])
        ext = sum(s["external"] for s in p["sets"])
        miss = sum(s["missing"] for s in p["sets"])
        age = int((time.time() - (p["mtime"] or 0)) / 86400)
        w(f"- {_short(p['path'], h)} — {human(p['alloc'])}, {sets} sets, {age}d old, {p['version'] or '?'}"
          + (f", {ext} external refs" if ext else "") + (f", {miss} missing" if miss else "")
          + (f", maybe a copy of {len(p['possible_copies'])} other(s)" if p["possible_copies"] else ""))
    if len(ov["projects"]) > 80:
        w(f"- … and {len(ov['projects']) - 80} more")
    if ov["loose_sets"]:
        w(f"Sets not inside a project folder ({len(ov['loose_sets'])}):")
        for s in ov["loose_sets"][:30]:
            w(f"- {_short(s['path'], h)}")
    w("")

    w("## Cleanup opportunities")
    groups = {}
    for f in purge.findings(con, cfg):
        g = groups.setdefault(f["group"], [0, 0, []])
        g[0] += 1
        g[1] += f["alloc"]
        g[2].append(f)
    for name, (n, total, items) in sorted(groups.items(), key=lambda x: -x[1][1]):
        w(f"- {name}: {n} items, {human(total)}")
        for f in sorted(items, key=lambda x: -x["alloc"])[:5]:
            w(f"    - {_short(f['path'], h)} ({human(f['alloc'])})")
    errs = con.execute("SELECT path, error FROM errors LIMIT 10").fetchall()
    if errs:
        w("")
        w("## Couldn't read (give Terminal Full Disk Access to include these)")
        for e in errs:
            w(f"- {_short(e['path'], h)}: {e['error']}")
    return "\n".join(L) + "\n"


def write(con, cfg: dict) -> str:
    text = build(con, cfg)
    p = config.app_dir() / "survey.md"
    p.write_text(text)
    return str(p)
