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

SCHOOL_WORDS = (r"(\b[A-Z]{2,4} ?\d{3}[A-Z]?\b|syllabus|homework|assignment|lecture|midterm|"
                r"\bfinal exam\b|\bquiz\b|textbook|\bcourse\b|\bschool\b)")
MONEY_WORDS = (r"(\btax(es)?\b|\b1099s?\b|\bw-?2\b|invoice|receipt|pay ?stub|payslip|\bstatement\b|"
               r"gusto|\brefund\b)")

# Rules are checked top to bottom against each item in an inbox; the first match
# produces the suggestion. "dest" templates may use {cloud} {ableton} {home}
# {year} {month} {category} {library}. Rules with "auto": true are applied by `autosort`.
# "enabled": false switches a rule off. Trash rules only ever match single
# files (never folders), and their "risk" ("safe"/"review") is shown next to
# the suggestion.
# Bump when the default rules change, so saved settings pick up the new ones.
RULES_VERSION = 4  # 4: School and Money documents

DEFAULT_CONFIG = {
    "rules_version": RULES_VERSION,
    "inboxes": ["~/Downloads", "~/Desktop"],
    # Inboxes you actively work out of: items there are left alone until stale.
    "active_inboxes": ["~/Desktop"],
    "cloud_root": "~/" + ICLOUD_REL,
    "ableton_root": "{cloud}/Ableton Projects",
    # Sub-folders of ableton_root used as status buckets for projects.
    "ableton_buckets": ["Active", "Ideas", "Finished", "Archive"],
    # The music library: one folder everything music-related is filed under, so
    # it can move as a whole later. Unset until you set it up in the Plan tab.
    # A rekordbox collection export (File → Export Collection in xml format): its tracks stay put.
    "rekordbox_xml": "",
    "library_root": "{cloud}",
    "library_ready": False,
    # Folder names inside the library (and two document homes).
    "layout": {
        "projects": "Projects",
        "statuses": ["Active", "Dormant", "Finished", "Archive"],
        "releases": "Releases",
        "work": "Work",
        "samples": "Samples",
        "source_tracks": "Samples/Source Tracks",
        "brand": "Brand",
        "exports": "Exports",
        # Broken projects you've marked "Archive as broken": a folder of their own.
        "broken": "Broken Projects",
        "school": "{cloud}/Documents/School",
        "money": "{cloud}/Documents/Money",
    },
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
        {"name": "School", "when": {"name_regex": SCHOOL_WORDS},
         "describe": "school work: course codes like ENG101, syllabus, homework, lecture slides",
         "action": "move", "dest": "{cloud}/Documents/School"},
        {"name": "Money", "when": {"name_regex": MONEY_WORDS},
         "describe": "taxes, 1099s, W-2s, invoices, receipts, pay stubs and statements",
         "action": "move", "dest": "{cloud}/Documents/Money"},
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


def _fill(template: str, values: dict) -> str:
    for _ in range(3):
        for k, v in values.items():
            template = template.replace("{" + k + "}", str(v))
    return template


def library_paths(cfg: dict) -> dict:
    """The library's folders as real paths: root, projects, status folders, samples..."""
    lay = {**DEFAULT_CONFIG["layout"], **(cfg.get("layout") or {})}
    root = expand("{library}", cfg)
    out = {"root": str(root), "ready": bool(cfg.get("library_ready"))}
    for k in ("projects", "releases", "work", "samples", "source_tracks", "brand"):
        out[k] = str(root / lay[k])
    out["broken"] = str(root / lay["broken"])
    if out["ready"]:
        out["statuses"] = {s: str(root / lay["projects"] / s) for s in lay["statuses"]}
    else:  # until it's set up, projects go where the Ableton tab already files them
        proj = expand(cfg["ableton_root"], cfg)
        out["projects"] = str(proj)
        out["statuses"] = {s: str(proj / s) for s in cfg.get("ableton_buckets") or lay["statuses"]}
        out["broken"] = str(proj / lay["broken"])
    out["exports"] = lay["exports"]
    out["school"] = str(expand(lay["school"], cfg))
    out["money"] = str(expand(lay["money"], cfg))
    return out


def set_up_library(cfg: dict, root: str, statuses: list | None = None) -> dict:
    """Point the library at an existing folder in your home folder and use its
    Projects/<status> folders for the Ableton tab too."""
    path = Path(os.path.expanduser(root)).resolve()
    if not path.is_dir():
        raise ValueError(f"{root} isn't a folder")
    if not (str(path) + os.sep).startswith(str(home().resolve()) + os.sep):
        raise ValueError("The library has to be inside your home folder")
    statuses = [s.strip() for s in (statuses or []) if s and s.strip()]
    if any("/" in s or s.startswith(".") for s in statuses):
        raise ValueError("Status folder names can't contain / or start with a dot")
    cfg = copy.deepcopy(cfg)
    cloud = os.path.realpath(expand("{cloud}", cfg))
    shown = os.path.realpath(path)
    cfg["library_root"] = "{cloud}" + shown[len(cloud):] if (shown + os.sep).startswith(cloud + os.sep) or shown == cloud \
        else str(path)
    cfg["layout"] = {**DEFAULT_CONFIG["layout"], **(cfg.get("layout") or {})}
    if statuses:
        cfg["layout"]["statuses"] = statuses
    cfg["ableton_root"] = "{library}/" + cfg["layout"]["projects"]
    cfg["ableton_buckets"] = list(cfg["layout"]["statuses"])
    # Rules that filed into a status folder you don't have now use the first one.
    first = cfg["ableton_buckets"][0]
    for r in cfg.get("rules", []):
        dest = r.get("dest") or ""
        if dest.startswith("{ableton}/") and dest[len("{ableton}/"):].split("/")[0] not in cfg["ableton_buckets"]:
            r["dest"] = "{ableton}/" + first + dest[len("{ableton}/"):][len(dest[len("{ableton}/"):].split("/")[0]):]
    cfg["library_ready"] = True
    return cfg


def expand(path: str, cfg: dict | None = None, **extra) -> Path:
    """Expand ~ and {cloud}/{ableton}/{home}/... placeholders into a Path."""
    cfg = cfg or load_config()
    cloud = os.path.expanduser(cfg["cloud_root"].replace("{home}", str(home())))
    values = {"home": str(home()), "cloud": cloud}
    values["library"] = _fill(cfg.get("library_root") or "{cloud}", values)
    values["ableton"] = _fill(cfg["ableton_root"], values)
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
