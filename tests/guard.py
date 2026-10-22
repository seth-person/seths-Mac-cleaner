"""Keeps the tests away from the real Mac they run on.

Imported first by every test module. Commands that act on this Mac rather than
on files (quitting or opening apps, the Keychain, privacy permissions, the app
registry) are replaced by stand-ins that only note they were called, and the
installer and updater are told they're in a sandbox. Reading commands (pgrep,
tmutil, codesign) are left alone.
"""
import os
import stat
import tempfile
from pathlib import Path

STAND_INS = ("osascript", "open", "security", "tccutil", "lsregister", "killall", "pkill")

_bin = Path(tempfile.mkdtemp(prefix="macclean-test-bin-"))
CALLS = _bin / "calls.txt"
for _tool in STAND_INS:
    _p = _bin / _tool
    _p.write_text(f'#!/bin/bash\necho "{_tool} $*" >> "{CALLS}"\nexit 0\n')
    _p.chmod(_p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

os.environ["PATH"] = f"{_bin}{os.pathsep}{os.environ.get('PATH', '')}"
os.environ["MACCLEAN_SANDBOX"] = "1"
os.environ["MACCLEAN_NO_REOPEN"] = "1"
os.environ["MACCLEAN_NO_LAUNCH"] = "1"


def calls() -> str:
    """What the stand-ins were asked to do so far."""
    return CALLS.read_text() if CALLS.exists() else ""
