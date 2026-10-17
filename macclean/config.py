"""Paths and user configuration.

Everything lives in ~/.macclean (override with MACCLEAN_HOME):
  config.json   - inboxes, destinations, triage rules (editable in the dashboard)
  scan.db       - SQLite snapshot of the last scan
  actions.jsonl - log of every move/trash, used for undo
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

ICLOUD_REL = "Library/Mobile Documents/com~apple~CloudDocs"


def home() -> Path:
    return Path(os.path.expanduser("~"))


def app_dir() -> Path:
    d = Path(os.environ.get("MACCLEAN_HOME") or home() / ".macclean")
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return app_dir() / "scan.db"


def actions_log_path() -> Path:
    return app_dir() / "actions.jsonl"


def config_path() -> Path:
    return app_dir() / "config.json"


# Rules are checked top to bottom against each item in an inbox; the first match
# produces the suggestion. "dest" templates may use {cloud} {ableton} {home}
# {year} {month} {category}. Rules with "auto": true are applied by `autosort`.
DEFAULT_CONFIG = {
    "inboxes": ["~/Downloads", "~/Desktop"],
    # Inboxes you actively work out of: items there are left alone until stale.
    "active_inboxes": ["~/Desktop"],
    "cloud_root": "~/" + ICLOUD_REL,
    "ableton_root": "{cloud}/Ableton Projects",
    # Sub-folders of ableton_root used as status buckets for projects.
    "ableton_buckets": ["Active", "Ideas", "Finished", "Archive"],
    "stale_days": 21,
    "scan_roots": ["~"],
    "exclude": [
        "/System/Volumes", "/Volumes", "/dev", "/proc", "/sys",
        "~/Library/Mobile Documents/com~apple~CloudDocs/.Trash",
    ],
    # Files smaller than this are counted but not stored individually
    # (inbox files, Ableton sets and audio are always stored).
    "min_file_mb": 1,
    "rules": [
        {"name": "Unfinished downloads", "when": {"ext": [".crdownload", ".download", ".part", ".partial"], "older_than_days": 2},
         "action": "trash", "auto": False},
        {"name": "Installers already used", "when": {"category": ["installer"], "older_than_days": 3},
         "action": "trash", "auto": False},
        {"name": "Old screenshots", "when": {"name_regex": r"^(Screenshot|Screen Shot|Screen Recording)\b", "older_than_days": 14},
         "action": "trash", "auto": False},
        {"name": "Ableton projects", "when": {"kind": ["ableton-project"]},
         "action": "move", "dest": "{ableton}/Active"},
        {"name": "Loose Ableton sets", "when": {"ext": [".als"]},
         "action": "move", "dest": "{ableton}/Ideas"},
        {"name": "Sample packs & presets", "when": {"category": ["audio"], "kind": ["folder"]},
         "action": "move", "dest": "{cloud}/Music/Samples"},
        {"name": "Ableton packs & presets", "when": {"ext": [".alp", ".adg", ".adv", ".alc", ".ams"]},
         "action": "move", "dest": "{cloud}/Music/Ableton Library"},
        {"name": "Bounces & audio", "when": {"category": ["audio"]},
         "action": "move", "dest": "{cloud}/Music/Bounces/{year}"},
        {"name": "Plugins", "when": {"category": ["plugin"]},
         "action": "move", "dest": "{cloud}/Music/Plugin Installers"},
        {"name": "Images", "when": {"category": ["image"]},
         "action": "move", "dest": "{cloud}/Pictures/{year}"},
        {"name": "Video", "when": {"category": ["video"]},
         "action": "move", "dest": "{cloud}/Videos/{year}"},
        {"name": "Documents", "when": {"category": ["document"]},
         "action": "move", "dest": "{cloud}/Documents/{year}"},
        {"name": "Code", "when": {"category": ["code"]},
         "action": "move", "dest": "~/Developer"},
        {"name": "Archives", "when": {"category": ["archive"]},
         "action": "move", "dest": "{cloud}/Archives/{year}"},
    ],
}


def load_config() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    p = config_path()
    if p.exists():
        try:
            user = json.loads(p.read_text())
            cfg.update(user)
        except (OSError, ValueError):
            pass
    return cfg


def save_config(cfg: dict) -> None:
    validate_config(cfg)
    tmp = config_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    os.replace(tmp, config_path())


def validate_config(cfg: dict) -> None:
    if not isinstance(cfg.get("inboxes"), list) or not cfg["inboxes"]:
        raise ValueError("'inboxes' must be a non-empty list of folders")
    if not isinstance(cfg.get("rules"), list):
        raise ValueError("'rules' must be a list")
    for i, r in enumerate(cfg["rules"]):
        if r.get("action") not in ("move", "trash", "keep"):
            raise ValueError(f"rule {i + 1}: action must be move, trash or keep")
        if r.get("action") == "move" and not r.get("dest"):
            raise ValueError(f"rule {i + 1}: move rules need a 'dest'")
        if not isinstance(r.get("when", {}), dict):
            raise ValueError(f"rule {i + 1}: 'when' must be an object")


def expand(path: str, cfg: dict | None = None, **extra) -> Path:
    """Expand ~ and {cloud}/{ableton}/{home}/... placeholders into a Path."""
    cfg = cfg or load_config()
    cloud = os.path.expanduser(cfg["cloud_root"].replace("{home}", str(home())))
    values = {"home": str(home()), "cloud": cloud}
    values["ableton"] = cfg["ableton_root"].format(**values)
    values.update(extra)
    out = path
    if out.startswith("iCloud Drive"):  # the dashboard shows {cloud} this way
        out = "{cloud}" + out[len("iCloud Drive"):]
    for _ in range(3):  # placeholders may nest ({ableton} contains {cloud})
        for k, v in values.items():
            out = out.replace("{" + k + "}", str(v))
    return Path(os.path.expanduser(out))


def inbox_paths(cfg: dict) -> list:
    return [expand(p, cfg) for p in cfg["inboxes"]]
