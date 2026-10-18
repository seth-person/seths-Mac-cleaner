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


# Installers from audio software makers are worth keeping (one-time purchases,
# old versions), so they're filed rather than trashed.
PLUGIN_VENDORS = (r"(fabfilter|native.?instruments|native.?access|komplete|kontakt|izotope|ozone|neutron|serum|xfer|"
                  r"arturia|spitfire|u-he|valhalla|soundtoys|waves|plugin.?alliance|slate|output|splice|vital|"
                  r"ableton|toontrack|spectrasonics|omnisphere|eventide|sonnox|melda|kilohearts|cableguys|"
                  r"\b(vst3?|au|aax)\b)")

# Rules are checked top to bottom against each item in an inbox; the first match
# produces the suggestion. "dest" templates may use {cloud} {ableton} {home}
# {year} {month} {category}. Rules with "auto": true are applied by `autosort`.
# "enabled": false switches a rule off. Trash rules only ever match single
# files (never folders), and their "risk" ("safe"/"review") is shown next to
# the suggestion.
# Bump when the default rules change, so saved settings pick up the new ones.
RULES_VERSION = 3

DEFAULT_CONFIG = {
    "rules_version": RULES_VERSION,
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
        {"name": "Unfinished downloads", "when": {"kind": ["file"], "ext": [".crdownload", ".download", ".part", ".partial"], "older_than_days": 2},
         "action": "trash", "risk": "safe", "auto": False},
        {"name": "Plugin & instrument installers",
         "when": {"category": ["installer"], "name_regex": PLUGIN_VENDORS},
         "action": "move", "dest": "{cloud}/Music/Plugin Installers"},
        {"name": "Installers already used", "when": {"kind": ["file"], "category": ["installer"], "older_than_days": 14},
         "action": "trash", "risk": "review", "auto": False},
        {"name": "Old screenshots", "when": {"kind": ["file"], "name_regex": r"^(Screenshot|Screen Shot|Screen Recording)\b", "older_than_days": 30},
         "action": "move", "dest": "{cloud}/Pictures/Screenshots/{year}"},
        {"name": "Ableton projects", "when": {"kind": ["ableton-project"]},
         "action": "move", "dest": "{ableton}/Active"},
        {"name": "Loose Ableton sets", "when": {"ext": [".als"]},
         "action": "move", "dest": "{ableton}/Ideas"},
        {"name": "Sample packs & presets", "when": {"category": ["audio"], "kind": ["folder"]},
         "action": "move", "dest": "{cloud}/Music/Samples"},
        {"name": "Ableton packs & presets", "when": {"ext": [".alp", ".adg", ".adv", ".alc", ".ams"]},
         "action": "move", "dest": "{cloud}/Music/Ableton Library"},
        # Audio files, in this order (first match wins):
        {"name": "Downloaded tracks (FLAC)", "when": {"kind": ["file"], "ext": [".flac"]},
         "describe": "FLAC files (tracks you downloaded to listen to or sample; you never bounce FLAC)",
         "action": "move", "dest": "{cloud}/Music/Samples/Source Tracks"},
        {"name": "Finished masters", "when": {"kind": ["file"], "category": ["audio"], "name_regex": r"\bMASTER\b",
                                              "match_case": True},
         "describe": "audio files with MASTER (in capitals) in the name, e.g. “Song (MASTER 24-bit 48k).wav”",
         "action": "move", "dest": "{cloud}/Music/Releases"},
        {"name": "My bounces", "when": {"kind": ["file"], "category": ["audio"], "name_regex": r"\bv\d+\b"},
         "describe": "audio files with a version number like V10 or v3, e.g. “Blackout Remix V10.wav”",
         "action": "move", "dest": "{cloud}/Music/Bounces/{year}"},
        {"name": "Stems & sketches", "when": {"kind": ["file"], "category": ["audio"]},
         "describe": "any other audio files (pieces of tracks, stems, sketches)",
         "action": "move", "dest": "{cloud}/Music/Bounces/Stems & Sketches/{year}"},
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
        except (OSError, ValueError):
            return cfg
        if user.get("rules_version", 0) < RULES_VERSION:
            user["rules"] = migrate_rules(user.get("rules", []))
            user["rules_version"] = RULES_VERSION
        cfg.update(user)
    return cfg


def migrate_rules(saved: list) -> list:
    """New default rules replace old ones, keeping what the person changed:
    on/off, day counts, destinations and "auto" for rules with the same name,
    plus any rules they wrote themselves (added at the end)."""
    defaults = copy.deepcopy(DEFAULT_CONFIG["rules"])
    default_names = {r["name"] for r in defaults}
    old_defaults = {"Installers already used", "Old screenshots", "Unfinished downloads"}  # behaviour changed
    by_name = {r.get("name"): r for r in saved}
    for r in defaults:
        mine = by_name.get(r["name"])
        if not mine:
            continue
        if "enabled" in mine:
            r["enabled"] = mine["enabled"]
        if mine.get("auto") and r["action"] != "trash":
            r["auto"] = True
        if r["action"] == "move" and mine.get("action") == "move" and mine.get("dest"):
            r["dest"] = mine["dest"]
        days = (mine.get("when") or {}).get("older_than_days")
        if days is not None and "older_than_days" in r["when"] and r["name"] not in old_defaults:
            r["when"]["older_than_days"] = days
    retired = {"Bounces & audio"}  # replaced by the four audio rules (v3)
    custom = [r for r in saved if r.get("name") not in default_names and r.get("name") not in retired]
    return defaults + custom


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
