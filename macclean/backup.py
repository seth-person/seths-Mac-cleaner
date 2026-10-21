"""When this Mac was last backed up with Time Machine, for the reminder shown
before big batches. Read-only: it only asks `tmutil`, and never blocks anything."""
from __future__ import annotations

import re
import subprocess
import sys
import time
from datetime import datetime

REMIND_AFTER_DAYS = 7
BIG_BATCH_ITEMS = 50
BIG_BATCH_BYTES = 10e9

_cache = {}


def _from_tmutil() -> float | None:
    try:
        r = subprocess.run(["tmutil", "latestbackup"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2}-\d{6})", r.stdout or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d-%H%M%S").timestamp()
    except ValueError:
        return None


def status() -> dict:
    """{'supported', 'last' (timestamp or None), 'days' (since last, or None), 'remind'}"""
    hit = _cache.get("status")
    if hit and time.time() - hit[1] < 600:
        return hit[0]
    if sys.platform != "darwin":
        out = {"supported": False, "last": None, "days": None, "remind": False}
    else:
        last = _from_tmutil()
        days = (time.time() - last) / 86400 if last else None
        out = {"supported": True, "last": last, "days": days,
               "remind": days is None or days > REMIND_AFTER_DAYS}
    _cache["status"] = (out, time.time())
    return out
