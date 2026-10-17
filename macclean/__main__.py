"""macclean command line.

  python3 -m macclean                # open the dashboard (default)
  python3 -m macclean scan [roots…]  # scan from the terminal (default root: ~)
  python3 -m macclean survey         # write ~/.macclean/survey.md from the last scan
  python3 -m macclean autosort [--apply]   # run rules marked "auto": true
"""
from __future__ import annotations

import argparse
import sys

from . import config, db, inbox, survey
from .classify import human


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="macclean", description="Keep your Mac's catch-all folders under control.")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="open the dashboard")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    sc = sub.add_parser("scan", help="scan the disk")
    sc.add_argument("roots", nargs="*", help="folders to scan (default: config scan_roots, i.e. ~). Use / for everything.")
    sub.add_parser("survey", help="write a text summary of the last scan")
    a = sub.add_parser("autosort", help='apply rules marked "auto": true (dry run unless --apply)')
    a.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd in (None, "serve"):
        from .server import serve
        serve(getattr(args, "port", 8765), not getattr(args, "no_browser", False))
        return 0

    cfg = config.load_config()
    if args.cmd == "scan":
        from .scanner import Scanner

        def progress(st):
            sys.stderr.write(f"\r{st['phase']:<22} {st['files']:>10,} files  {human(st['bytes']):>9}  "
                             f"{st['current'][-60:]:<60}")
            sys.stderr.flush()

        Scanner(cfg, args.roots or None, progress).run()
        sys.stderr.write("\n")
        print(f"Scan saved to {config.db_path()}")
        args.cmd = "survey"

    if args.cmd == "survey":
        if not db.has_scan():
            print("No scan yet: run `python3 -m macclean scan` first.")
            return 1
        path = survey.write(db.connect(), cfg)
        print(f"Survey written to {path}")
        return 0

    if args.cmd == "autosort":
        results = inbox.autosort(cfg, dry_run=not args.apply)
        if not results:
            print('Nothing to do (no items match a rule with "auto": true).')
        for r in results:
            if r["ok"]:
                print(f"{'would ' if r.get('dry_run') else ''}{r['op']}: {r['src']} -> {r['dst']}")
            else:
                print(f"skipped {r['path']}: {r['error']}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
