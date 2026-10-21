"""Local dashboard server (http://127.0.0.1:8765).

Only listens on localhost. Every request that changes something must carry
the per-launch token embedded in the page, so other websites open in your
browser can't drive it.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, ableton, actions, backup, config, db, exports, inbox, listen, live_prefs, marks, plan, purge, safety, survey, updater
from .scanner import BackgroundScan

STATIC = Path(__file__).parent / "static"
TOKEN = secrets.token_urlsafe(24)
SCAN = BackgroundScan()
HTTPD = None
_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
          ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}


def _con():
    return db.connect() if db.has_scan() else None


def api_status(q):
    con = _con()
    m = db.meta(con) if con else {}
    import shutil
    du = shutil.disk_usage("/")
    return {"scan": SCAN.status(), "has_scan": bool(m), "meta": m,
            "disk": {"total": du.total, "used": du.used, "free": du.free},
            "home": str(config.home()), "platform": sys.platform,
            "app": "macclean", "version": __version__, "mode": updater.mode()}


def api_overview(q):
    con = _con()
    cfg = config.load_config()
    if not con:
        return {"has_scan": False}
    cats = [dict(r) for r in con.execute(
        "SELECT category, SUM(alloc) alloc, SUM(size) size, SUM(count) count FROM cat_stats GROUP BY category")]
    exts = [dict(r) for r in con.execute(
        "SELECT category, ext, alloc, size, count FROM cat_stats ORDER BY alloc DESC LIMIT 40")]
    h = str(config.home())
    top_dirs = [dict(r) for r in con.execute(
        "SELECT path, name, alloc, size, files, kind, zone FROM dirs WHERE parent=? ORDER BY alloc DESC LIMIT 12", (h,))]
    big_files = [dict(r) for r in con.execute(
        "SELECT path, name, category, alloc, mtime FROM files WHERE dataless=0 ORDER BY alloc DESC LIMIT 15")]
    cloud = str(config.expand(cfg["cloud_root"], cfg))
    cloud_row = con.execute("SELECT size, alloc, files FROM dirs WHERE path=?", (cloud,)).fetchone()
    errors = [dict(r) for r in con.execute("SELECT path, error FROM errors LIMIT 50")]
    return {"has_scan": True, "categories": cats, "extensions": exts, "top_dirs": top_dirs,
            "big_files": big_files, "cloud": dict(cloud_row) if cloud_row else None,
            "cloud_path": cloud, "errors": errors, "meta": db.meta(con)}


def api_tree(q):
    con = _con()
    if not con:
        return {"has_scan": False}
    m = db.meta(con)
    roots = json.loads(m.get("roots", "[]"))
    path = q.get("path", [None])[0] or (roots[0] if roots else str(config.home()))
    node = con.execute("SELECT * FROM dirs WHERE path=?", (path,)).fetchone()
    if not node:
        return {"error": f"{path} isn't in the last scan", "roots": roots}
    kids = [dict(r) for r in con.execute(
        "SELECT path, name, alloc, size, files, kind, zone, mtime FROM dirs WHERE parent=? AND path != ? "
        "ORDER BY alloc DESC LIMIT 400", (path, path))]
    files = [dict(r, kind="file") for r in con.execute(
        "SELECT path, name, alloc, size, category, mtime, dataless FROM files WHERE parent=? "
        "ORDER BY alloc DESC LIMIT 200", (path,))]
    crumbs = []
    p = path
    while True:
        crumbs.append(p)
        if p in roots or p == os.path.dirname(p):
            break
        p = os.path.dirname(p)
    return {"node": dict(node), "children": kids, "files": files, "crumbs": list(reversed(crumbs)),
            "roots": roots}


def api_inbox(q):
    cfg = config.load_config()
    con = _con()
    data = inbox.list_inboxes(cfg)
    inbox.mark_used_by_sets(data, con, cfg)
    data["destinations"] = inbox.destinations(con, cfg)
    return data


def api_destinations(q):
    return {"destinations": inbox.destinations(_con(), config.load_config())}


def api_purge(q):
    con = _con()
    if not con:
        return {"has_scan": False}
    cfg = config.load_config()
    items = purge.findings(con, cfg)
    return {"has_scan": True, "findings": items, "groups": purge.GROUPS,
            "summary": purge.summary(con, cfg, items), "scanned_at": db.meta(con).get("scanned_at")}


def api_packs(q):
    con = _con()
    if not con:
        return {"has_scan": False}
    return {"has_scan": True, **ableton.packs_overview(con, config.load_config())}


def post_ableton_mark(body):
    if not isinstance(body.get("path"), str) or not os.path.isabs(body["path"]):
        return {"ok": False, "error": "Pick a project to mark"}
    marks.set_important(body["path"], bool(body.get("important")))
    return {"ok": True}


def post_ableton_recheck(body):
    con = _con()
    if not con:
        return {"ok": False, "error": "Scan first"}
    known = con.execute("SELECT 1 FROM dirs WHERE kind='ableton-project' AND path=?", (body.get("project"),)).fetchone()
    if not known:
        return {"ok": False, "error": "That isn't a project from the last scan. Rescan to pick it up."}
    try:
        res = ableton.recheck_project(con, body["project"])
    except (OSError, KeyError) as e:
        return {"ok": False, "error": str(e)}
    # The refreshed project, shaped like /api/ableton's, so the page can update just that row.
    ov = ableton.overview(con, config.load_config())
    res["item"] = next((p for p in ov["projects"] if p["path"] == body["project"]), None)
    res["needs_collect"] = ov["totals"]["needs_collect"]
    return {"ok": True, **res}


def post_ableton_open(body):
    """Open a set in Live (whatever app opens .als files). Only sets from the last scan."""
    path = body.get("path")
    con = _con()
    if not con or not isinstance(path, str) or not path.lower().endswith(".als"):
        return {"ok": False, "error": "Pick a set to open"}
    if not con.execute("SELECT 1 FROM ableton_sets WHERE path=?", (path,)).fetchone():
        return {"ok": False, "error": "That set isn't in the last scan. Rescan to pick it up."}
    if not os.path.isfile(path):
        return {"ok": False, "error": "That set isn't there any more. Rescan to update the list."}
    if sys.platform != "darwin":
        return {"ok": False, "error": "Opening sets in Live only works on macOS"}
    r = subprocess.run(["open", path], capture_output=True, text=True, check=False)
    return {"ok": r.returncode == 0, "error": (r.stderr or "Live couldn't open it").strip() if r.returncode else None}


def api_ableton_set(q):
    """What you can listen to for one set: every matching export, and the audio it uses."""
    con = _con()
    path = (q.get("path") or [""])[0]
    row = con.execute("SELECT project FROM ableton_sets WHERE path=?", (path,)).fetchone() if con else None
    if not row:
        return {"error": "That set isn't in the last scan. Rescan to pick it up."}
    project = row["project"]
    name = os.path.basename(project) if project else None
    return {"path": path, "bounces": listen.bounces_for(con, path, name, limit=None),
            "ingredients": listen.ingredients(con, path, project)}


def api_ableton(q):
    con = _con()
    if not con:
        return {"has_scan": False}
    cfg = config.load_config()
    data = ableton.overview(con, cfg)
    data["exports"] = exports.attach_checklist(con, cfg, data["projects"])
    data["tracks_rescan_needed"] = int(db.meta(con).get("index_version", 0) or 0) < 3
    data["live_pins"] = live_prefs.pinned_folders()
    data["template_problem"] = live_prefs.template_problem()
    return {"has_scan": True, **data}


def post_ableton_flag(body):
    if not isinstance(body.get("path"), str) or not os.path.isabs(body["path"]) or body.get("flag") not in ("no_master",):
        return {"ok": False, "error": "Pick a project"}
    marks.set_flag(body["path"], body["flag"], bool(body.get("on")))
    return {"ok": True}


def api_plan(q):
    cfg = config.load_config()
    con = _con()
    folder = (q.get("folder") or [""])[0]
    out = {"places": plan.places(con, cfg), "library": config.library_paths(cfg), "has_scan": con is not None,
           "setup": api_library(q), "layout": {**config.DEFAULT_CONFIG["layout"], **(cfg.get("layout") or {})}}
    if folder:
        out.update(plan.plan_folder(con, cfg, folder))
    return out


def post_plan_save(body):
    try:
        return {"ok": True, **plan.save_decisions(body["folder"], body.get("decisions") or {})}
    except (KeyError, ValueError, OSError) as e:
        return {"ok": False, "error": str(e)}


def post_plan_preview(body):
    items = body.get("items")
    if not isinstance(items, list):
        return {"ok": False, "error": "Nothing to preview"}
    return {"ok": True, "results": plan.preview(items, config.load_config())}


def api_library(q):
    cfg = config.load_config()
    cloud = config.expand("{cloud}", cfg)
    suggestions = [str(p) for p in (cloud / "Active Storage", cloud / "Music Library", cloud) if p.is_dir()]
    return {"library": config.library_paths(cfg), "suggestions": suggestions,
            "statuses": config.library_paths(cfg)["statuses"]}


def post_library(body):
    try:
        cfg = config.set_up_library(config.load_config(), str(body.get("root") or ""), body.get("statuses"))
        config.save_config(cfg)
        return {"ok": True, "library": config.library_paths(cfg)}
    except (ValueError, OSError) as e:
        return {"ok": False, "error": str(e)}


def api_config(q):
    cfg = config.load_config()
    return {"config": cfg, "path": str(config.config_path()),
            "cloud_path": str(config.expand(cfg["cloud_root"], cfg)),
            "ableton_path": str(config.expand(cfg["ableton_root"], cfg)),
            "defaults": config.DEFAULT_CONFIG}


def api_history(q):
    return {"history": actions.history(), "batches": actions.batches(),
            "interrupted": actions.interrupted_batches()}


def api_backup(q):
    return backup.status()


def post_undo_batch(body):
    try:
        return {"ok": True, **actions.undo_batch(body["id"])}
    except (actions.ActionError, KeyError) as e:
        return {"ok": False, "error": str(e)}


def post_resume_batch(body):
    try:
        results = actions.resume_batch(body["id"])
    except (actions.ActionError, KeyError) as e:
        return {"ok": False, "error": str(e)}
    con = _con()
    return {"ok": True, "results": results, "verify": ableton.verify_moves(con, results)}


def api_survey(q):
    con = _con()
    if not con:
        return {"has_scan": False}
    cfg = config.load_config()
    return {"text": survey.build(con, cfg), "path": survey.write(con, cfg)}


def api_update(q):
    return updater.check(force=q.get("force", ["0"])[0] == "1")


def _port():
    return HTTPD.server_address[1] if HTTPD else 8765


def post_update_install(body):
    try:
        res = updater.install_latest()
    except updater.UpdateError as e:
        return {"ok": False, "error": str(e)}
    _after_update(res)
    return {"ok": True, **res}


def post_update_rollback(body):
    try:
        res = updater.rollback()
    except updater.UpdateError as e:
        return {"ok": False, "error": str(e)}
    _after_update(res)
    return {"ok": True, **res}


def _after_update(res):
    if res.get("relaunch"):
        updater.exit_for_relaunch()  # the app quits; the swap script reopens it
    else:
        updater.restart_later(_port())


def post_update_migrate(body):
    try:
        res = updater.migrate_to_app()
    except updater.UpdateError as e:
        return {"ok": False, "error": str(e)}
    post_quit({})  # the new app takes over from here
    return {"ok": True, **res}


def post_update_token(body):
    try:
        updater.save_token(body.get("token", ""))
    except updater.UpdateError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "check": updater.check(force=True)}


def post_quit(body):
    def stop():
        import time
        time.sleep(0.3)  # let this reply go out first
        HTTPD.shutdown()
    if HTTPD:
        threading.Thread(target=stop, daemon=True).start()
    return {"ok": True}


def post_scan(body):
    cfg = config.load_config()
    roots = body.get("roots") or None
    if not SCAN.start(cfg, roots):
        return {"ok": False, "error": "A scan is already running"}
    return {"ok": True}


def post_cancel(body):
    SCAN.cancel()
    return {"ok": True}


def post_apply(body):
    cfg = config.load_config()
    con = _con()
    used = safety.UsedIndex(con)
    plain, results = [], []
    for it in body.get("items", []):
        # The scan may be out of date: re-check every trash at the moment of the click.
        scanned = None
        if con is not None:
            row = con.execute("SELECT size, mtime FROM files WHERE path=?", (it.get("path"),)).fetchone()
            scanned = dict(row) if row else None
        problem = safety.preflight(used, it.get("path", ""), it.get("action", ""), scanned)
        if problem:
            results.append({"ok": False, "path": it.get("path"), "error": f"Skipped: {problem}"})
        elif it.get("action") == "trash-asd":
            results.extend(purge.trash_asd(it["path"], cfg))
        else:
            plain.append(it)
    moved = actions.apply(plain, cfg, dry_run=bool(body.get("dry_run")), label=str(body.get("label") or ""))
    results.extend(moved)
    return {"results": results, "verify": ableton.verify_moves(con, moved)}


def post_open_trash(body):
    if sys.platform == "darwin":
        subprocess.run(["open", str(config.home() / ".Trash")], check=False)
        return {"ok": True}
    return {"ok": False, "error": "Opening the Trash only works on macOS"}


def post_undo(body):
    try:
        return {"ok": True, "entry": actions.undo(body["id"])}
    except actions.ActionError as e:
        return {"ok": False, "error": str(e)}


def post_config(body):
    try:
        config.save_config(body["config"])
        return {"ok": True}
    except (ValueError, KeyError, TypeError) as e:
        return {"ok": False, "error": str(e)}


def post_reveal(body):
    path = body.get("path", "")
    if not os.path.lexists(path):
        return {"ok": False, "error": "Not found"}
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", path], check=False)
        return {"ok": True}
    return {"ok": False, "error": "Reveal in Finder only works on macOS"}


GET = {"/api/status": api_status, "/api/overview": api_overview, "/api/tree": api_tree,
       "/api/inbox": api_inbox, "/api/destinations": api_destinations, "/api/purge": api_purge, "/api/ableton": api_ableton, "/api/ableton/set": api_ableton_set, "/api/packs": api_packs,
       "/api/config": api_config, "/api/history": api_history, "/api/survey": api_survey,
       "/api/update": api_update, "/api/backup": api_backup, "/api/plan": api_plan, "/api/library": api_library}
POST = {"/api/scan": post_scan, "/api/scan/cancel": post_cancel, "/api/apply": post_apply,
        "/api/undo": post_undo, "/api/undo-batch": post_undo_batch, "/api/resume-batch": post_resume_batch, "/api/config": post_config, "/api/reveal": post_reveal, "/api/open-trash": post_open_trash,
        "/api/ableton/mark": post_ableton_mark, "/api/ableton/recheck": post_ableton_recheck,
        "/api/ableton/open": post_ableton_open, "/api/ableton/flag": post_ableton_flag,
        "/api/plan/save": post_plan_save, "/api/plan/preview": post_plan_preview, "/api/library": post_library,
        "/api/update/install": post_update_install, "/api/update/rollback": post_update_rollback,
        "/api/update/token": post_update_token, "/api/update/migrate": post_update_migrate, "/api/quit": post_quit}


class Handler(BaseHTTPRequestHandler):
    server_version = "macclean"

    def log_message(self, fmt, *args):
        if os.environ.get("MACCLEAN_VERBOSE"):
            super().log_message(fmt, *args)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, default=str).encode())

    def _audio(self, q):
        """Stream an audio file for the in-app player, with byte ranges so it can seek."""
        con = _con()
        path = (q.get("path") or [""])[0]
        if (q.get("t") or [""])[0] != TOKEN:
            return self._send(403, b"forbidden", "text/plain")
        if not con or not listen.playable(con, path):
            return self._send(404, b"not found", "text/plain")
        size = os.path.getsize(path)
        start, end, code = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)$", (self.headers.get("Range") or "").strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            if start >= size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", listen.CONTENT_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream"))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(65536, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the player stopped or seeked elsewhere

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        u = urlparse(self.path)
        if u.path == "/api/audio":
            return self._audio(parse_qs(u.query))
        if u.path in GET:
            try:
                return self._json(GET[u.path](parse_qs(u.query)))
            except Exception as e:
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        name = "index.html" if u.path in ("/", "/index.html") else u.path.lstrip("/").replace("static/", "", 1)
        f = (STATIC / name).resolve()
        if not str(f).startswith(str(STATIC.resolve())) or not f.is_file():
            return self._send(404, b"not found", "text/plain")
        data = f.read_bytes()
        if name == "index.html":
            data = data.replace(b"__TOKEN__", TOKEN.encode())
        self._send(200, data, _TYPES.get(f.suffix, "application/octet-stream"))

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Macclean-Token") != TOKEN:
            return self._send(403, b"forbidden", "text/plain")
        u = urlparse(self.path)
        if u.path not in POST:
            return self._send(404, b"not found", "text/plain")
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            return self._json(POST[u.path](body))
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def make_server(port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def _already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=2) as r:
            return json.loads(r.read()).get("app") == "macclean"
    except (OSError, ValueError):
        return False


def _exit_with_parent() -> None:
    """Inside the Mac app: stop if the app goes away (crash, force quit)."""
    parent = os.getppid()

    def watch():
        import time
        while os.getppid() == parent:
            time.sleep(2)
        os._exit(0)
    threading.Thread(target=watch, daemon=True).start()


def serve(port: int = 8765, open_browser: bool = True) -> None:
    global HTTPD
    url = f"http://127.0.0.1:{port}/"
    try:
        HTTPD = make_server(port)
    except OSError:
        if _already_running(port):  # opened the app again: just show the page
            print(f"Mac Cleaner is already running at {url}")
            if open_browser:
                import webbrowser
                webbrowser.open(url)
            return
        raise
    url = f"http://127.0.0.1:{HTTPD.server_address[1]}/"
    print(f"Mac Cleaner {__version__} running at {url}  (Ctrl+C to stop)", flush=True)
    try:
        actions.recover()  # log anything a previous run moved but didn't get to log
    except OSError:
        pass
    if os.environ.get("MACCLEAN_APP_BUNDLE"):
        _exit_with_parent()
        threading.Thread(target=updater.reset_permissions_if_new_identity, daemon=True).start()
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        HTTPD.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        HTTPD.server_close()
