from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS dirs (
    path TEXT PRIMARY KEY, parent TEXT, name TEXT, depth INTEGER,
    size INTEGER, alloc INTEGER, files INTEGER, mtime REAL, kind TEXT, zone TEXT);
CREATE INDEX IF NOT EXISTS dirs_parent ON dirs(parent);
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY, parent TEXT, name TEXT, ext TEXT, category TEXT,
    size INTEGER, alloc INTEGER, mtime REAL, birth REAL, dataless INTEGER);
CREATE INDEX IF NOT EXISTS files_parent ON files(parent);
CREATE INDEX IF NOT EXISTS files_size ON files(size);
CREATE TABLE IF NOT EXISTS cat_stats (
    category TEXT, ext TEXT, count INTEGER, size INTEGER, alloc INTEGER,
    PRIMARY KEY (category, ext));
CREATE TABLE IF NOT EXISTS errors (path TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS dupes (grp INTEGER, hash TEXT, size INTEGER, path TEXT);
CREATE TABLE IF NOT EXISTS ableton_sets (
    path TEXT PRIMARY KEY, project TEXT, live_version TEXT, refs INTEGER,
    in_project INTEGER, packs INTEGER, external INTEGER, missing INTEGER,
    examples TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS ableton_presets (
    path TEXT PRIMARY KEY, project TEXT, live_version TEXT, refs INTEGER,
    in_project INTEGER, packs INTEGER, external INTEGER, missing INTEGER,
    examples TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS ableton_refs (set_path TEXT, ref_path TEXT);
CREATE TABLE IF NOT EXISTS ableton_pack_refs (user_path TEXT, pack TEXT, found INTEGER);
CREATE INDEX IF NOT EXISTS ableton_refs_ref ON ableton_refs(ref_path);
CREATE TABLE IF NOT EXISTS ableton_tracks (set_path TEXT, position INTEGER, name TEXT, kind TEXT);
CREATE INDEX IF NOT EXISTS ableton_tracks_set ON ableton_tracks(set_path);
"""


# Ableton projects in the scan. Scans made before 0.10 marked the User Library as
# one; it isn't, so it's left out here too.
PROJECTS = "kind='ableton-project' AND lower(name) <> 'user library'"


def connect(path: Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or config.db_path()), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def has_scan() -> bool:
    return config.db_path().exists()


def meta(con: sqlite3.Connection) -> dict:
    return {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM meta")}
