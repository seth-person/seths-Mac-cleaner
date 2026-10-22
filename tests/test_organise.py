"""Batches, the pre-move checks, the planning engine and export matching."""
import gzip
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard  # noqa: E402,F401  (first: keeps the tests off this Mac's apps and Keychain)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture  # noqa: E402

from macclean import (ableton, actions, backup, config, db, exports, inbox, live_prefs, marks,  # noqa: E402
                      plan, safety, server)
from macclean.scanner import Scanner  # noqa: E402

STEM = 3_276_800  # a few seconds of stereo audio: big enough to be a stem


def set_with_tracks(tracks, refs=()) -> bytes:
    """A set whose top-level tracks have names; refs go on the first track."""
    parts = ['<?xml version="1.0" encoding="UTF-8"?>\n<Ableton MajorVersion="5" Creator="Ableton Live 12.4.6"><LiveSet><Tracks>']
    for i, t in enumerate(tracks):
        parts.append(f'<AudioTrack Id="{i}"><Name><EffectiveName Value="{t}" /><UserName Value="{t}" /></Name>'
                     "<DeviceChain><MainSequencer><Sample><ArrangerAutomation><Events>")
        for abs_path, rel in (refs if i == 0 else ()):
            parts.append("<AudioClip><SampleRef><FileRef>"
                         f'<RelativePathType Value="3" /><RelativePath Value="{rel}" /><Path Value="{abs_path}" />'
                         "</FileRef></SampleRef></AudioClip>")
        parts.append("</Events></ArrangerAutomation></Sample></MainSequencer></DeviceChain></AudioTrack>")
    parts.append('<ReturnTrack Id="99"><Name><EffectiveName Value="A-Reverb" /></Name></ReturnTrack>')
    parts.append("</Tracks></LiveSet></Ableton>")
    return gzip.compress("".join(parts).encode())


def tracked_project(root: Path, name: str, tracks, age_days=1) -> Path:
    p = root / name
    fixture.write(p / "Ableton Project Info" / "Project8_1.cfg", b"cfg")
    s = fixture.write(p / "Samples" / "Imported" / "hit.wav", size=100_000, seed=len(name))
    set_name = name.replace(" Project", "")
    fixture.write(p / f"{set_name}.als", set_with_tracks(tracks, [(str(s), "Samples/Imported/hit.wav")]), age_days=age_days)
    return p


def stems(folder: Path, prefix: str, tracks, mix=True, age_days=1.0, seed=50) -> list:
    out = []
    for i, t in enumerate(tracks):
        out.append(fixture.write(folder / f"{prefix} {t}.wav", size=STEM, age_days=age_days, seed=seed + i))
    if mix:
        out.append(fixture.write(folder / f"{prefix}.wav", size=STEM, age_days=age_days, seed=seed + 99))
    return out


class Organise(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.home = Path(cls.tmp) / "home"
        cls._old = {k: os.environ.get(k) for k in ("HOME", "MACCLEAN_HOME")}
        os.environ["HOME"] = str(cls.home)
        os.environ.pop("MACCLEAN_HOME", None)
        cls._running = safety.app_running
        safety.app_running = lambda process: False  # don't depend on what's open on this machine
        fixture.build(cls.home)
        h, cloud = cls.home, cls.home / fixture.ICLOUD
        cls.cloud = cloud
        artist = cloud / "Active Storage" / "ARTIST" / "Completed Projects"
        cls.nightdrive = tracked_project(artist, "Night Drive Remix Project", ["Drums", "Bass", "Lead Synth", "Vox"])
        cls.songz = tracked_project(cloud / "Active Storage" / "Sorting" / "ACTIVE PROJECTS",
                                    "Song Z Project", ["Kick", "Snare", "Pad"])
        cls.loose = tracked_project(cloud / "Active Storage" / "Ableton Projects", "Loose Tune Project", ["Drums", "Bass", "Keys"])
        cls.tidy = tracked_project(cloud / "Active Storage" / "Ableton Projects", "Tidy Project", ["One", "Two", "Three"])
        fixture.write(cls.tidy / "Exports" / "Master" / "Tidy (MASTER).wav", size=1_500_000, seed=7)
        stems(cls.tidy / "Exports" / "Stems" / "2026-10-01 Tidy", "Tidy", ["One", "Two", "Three"], seed=80)
        # Exports to match: by name, by track names, by a Stem Prep record, and loose in Downloads.
        stems(h / "Downloads" / "Night Drive Remix Stems", "Night Drive Remix", ["Drums", "Bass", "Lead Synth", "Vox"])
        stems(h / "Desktop" / "Export Dump", "Party Mix", ["Drums", "Bass", "Lead Synth"], mix=False, seed=60, age_days=30)
        take = stems(h / "Downloads" / "stemprep export", "Take 1", ["Kick", "Snare", "Pad"], seed=70, age_days=0.5)
        stems(h / "Downloads", "Loose Tune", ["Drums", "Bass", "Keys"], mix=False, seed=90, age_days=2)
        stems(h / "Downloads" / "Mystery Stems", "Who Knows", ["Thing", "Other", "Third"], seed=120)
        fixture.write(h / "Downloads" / "Night Drive Remix (MASTER).wav", size=400_000, seed=5)
        fixture.write(h / "Downloads" / "Night Drive Remix V2.wav", size=400_000, seed=6, age_days=9)
        fixture.write(h / "Downloads" / "Night Drive Remix V10.wav", size=400_000, seed=8, age_days=2)
        fixture.write(h / "Downloads" / "ENG101 essay.pdf", b"%PDF-1.7 essay")
        fixture.write(h / "Downloads" / "2025 taxes.pdf", b"%PDF-1.7 taxes")
        fixture.write(h / "Downloads" / "Kick 128.wav", size=50_000, seed=3)
        # Stems you were sent: one lot dragged straight into a remix (its tracks are named after the
        # files), and one collected into the project; plus a second copy of stems already filed.
        cls.harbor = tracked_project(cloud / "Active Storage" / "Ableton Projects", "Harbor Remix Project",
                                     ["Harbor Remix Kick", "Harbor Remix Bass", "Harbor Remix Vox", "Pads"])
        stems(h / "Downloads" / "Harbor Parts", "Harbor Remix", ["Kick", "Bass", "Vox"], mix=False, seed=130, age_days=3)
        cls.cover = tracked_project(cloud / "Active Storage" / "Ableton Projects", "Cover Song Project", ["Guitar", "Keys"])
        sent = stems(cls.cover / "Samples" / "Imported", "Sent Parts", ["Gtr", "Piano", "Choir"], mix=False, seed=140)
        refs = [(str(f), "Samples/Imported/" + f.name) for f in sent]
        fixture.write(cls.cover / "Cover Song.als", set_with_tracks(["Guitar", "Keys"], refs), age_days=1)
        stems(h / "Downloads" / "Sent Parts", "Sent Parts", ["Gtr", "Piano", "Choir"], mix=False, seed=140, age_days=5)
        stems(h / "Desktop" / "Tidy stems copy", "Tidy", ["One", "Two", "Three"], seed=80)
        cls.oldremix = tracked_project(cloud / "Active Storage" / "Ableton Projects", "Old Remix Project",
                                       ["Lead", "Drum Bus", "Chords"], age_days=10)
        stems(h / "Downloads" / "Old Remix Pack", "Old Remix", ["Kick", "Bass", "Vox"], mix=False, seed=150, age_days=400)
        # A project whose samples went missing: two were found again elsewhere, one was in Google Drive.
        cls.lost = fixture.project(cloud / "Active Storage" / "Sorting" / "DORMANT PROJECTS", "Lost Song Project",
                                   samples=["here.wav"], missing=["snare 1.wav", "pad.wav"], age_days=800)
        fixture.write(cloud / "Active Storage" / "Sample Stash" / "Drums" / "snare 1.wav", size=30_000, seed=41)
        fixture.write(cloud / "Active Storage" / "Sample Stash" / "Keys" / "pad.wav", size=30_000, seed=42)
        drive_ref = ("/Users/olduser/My Drive/Samples/vocal.wav", "")
        lost_set = cls.lost / "Lost Song.als"
        refs = [(str(cls.lost / "Samples" / "Imported" / "here.wav"), "Samples/Imported/here.wav"),
                ("/Users/seth/Old Samples/snare 1.wav", "Samples/Imported/snare 1.wav"),
                ("/Users/seth/Old Samples/pad.wav", "Samples/Imported/pad.wav"), drive_ref]
        fixture.write(lost_set, fixture.als_xml(refs), age_days=800)
        # Another app's files: a rekordbox export and a Final Cut library that links to a video.
        cls.dj_track = fixture.write(h / "Downloads" / "Club Edit.aif", size=2_000_000, seed=31)
        fixture.write(h / "Documents" / "rekordbox.xml", (
            '<?xml version="1.0" encoding="UTF-8"?><DJ_PLAYLISTS Version="1.0.0"><COLLECTION Entries="1">'
            f'<TRACK TrackID="1" Name="Club Edit" Location="file://localhost{str(cls.dj_track).replace(" ", "%20")}"/>'
            '</COLLECTION><PLAYLISTS><NODE Type="0" Name="ROOT"/></PLAYLISTS></DJ_PLAYLISTS>').encode())
        cls.video = fixture.write(h / "Desktop" / "music video.mov", size=1_500_000, seed=32)
        media = h / "Movies" / "Videos.fcpbundle" / "Event" / "Original Media"
        media.mkdir(parents=True)
        os.symlink(cls.video, media / "music video.mov")
        created = os.path.getmtime(take[0]) - 30
        runs = h / "Library" / "Application Support" / "Ableton" / "Extensions Data" / "seth-person.stem-prep" / "stem-runs"
        offset = -time.timezone if not time.localtime(created).tm_isdst else -time.altzone
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(created)) + \
            ("+" if offset >= 0 else "-") + time.strftime("%H:%M", time.gmtime(abs(offset)))
        fixture.write(runs / "20261021-121756-Song Z.json", json.dumps({
            "format": 1, "extension_version": "0.1.0", "created_at": stamp, "song": "Song Z", "live_version": None,
            "range": {"start_beats": 0, "end_beats": 64, "tempo": 120, "source": "selection"},
            "tracks": [{"name": n, "kind": "audio", "muted": False, "in_group": ""} for n in ("Kick", "Snare", "Pad")],
            "main_effects_switched_off": ["Limiter"], "set_path": None}).encode())
        cls.cfg = config.load_config()
        Scanner(cls.cfg).run()
        cls.con = db.connect()
        exports._cache.clear()

    @classmethod
    def tearDownClass(cls):
        safety.app_running = cls._running
        cls.con.close()
        for k, v in cls._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.tmp)

    def scratch(self, name: str) -> Path:
        d = self.home / "Scratch" / name
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        return d


class BatchTests(Organise):
    def test_batch_is_one_undo(self):
        d = self.scratch("batch")
        files = [fixture.write(d / f"f{i}.txt", b"x") for i in range(3)]
        res = actions.apply([{"path": str(f), "action": "move", "dest": str(d / "out")} for f in files], self.cfg, label="Test batch")
        self.assertTrue(all(r["ok"] for r in res))
        bid = res[0]["batch"]
        b = next(b for b in actions.batches() if b["id"] == bid)
        self.assertEqual((b["label"], b["planned"], b["done"], b["finished"]), ("Test batch", 3, 3, True))
        out = actions.undo_batch(bid)
        self.assertEqual((out["undone"], out["failed"]), (3, []))
        self.assertTrue(all(f.exists() for f in files))
        self.assertEqual(next(b for b in actions.batches() if b["id"] == bid)["undone"], 3)

    def test_undo_batch_skips_what_changed_and_says_so(self):
        d = self.scratch("changed")
        a, b = fixture.write(d / "a.txt", b"a"), fixture.write(d / "b.txt", b"b")
        res = actions.apply([{"path": str(p), "action": "move", "dest": str(d / "out")} for p in (a, b)], self.cfg)
        fixture.write(a, b"someone made a new one here")
        out = actions.undo_batch(res[0]["batch"])
        self.assertEqual(out["undone"], 1)
        self.assertEqual(len(out["failed"]), 1)
        self.assertEqual(a.read_bytes(), b"someone made a new one here")  # never overwritten

    def test_a_move_that_was_not_logged_is_recovered(self):
        d = self.scratch("recover")
        src = fixture.write(d / "song.wav", b"audio")
        dst = d / "out" / "song.wav"
        entry = {"id": "abc123", "ts": "2026-10-21 12:00:00", "op": "move", "src": str(src), "dst": str(dst),
                 "note": "", "batch": None}
        with open(config.app_dir() / "journal.jsonl", "a") as f:  # noted, moved, then the app stopped
            f.write(json.dumps({"pending": entry}) + "\n")
        dst.parent.mkdir(parents=True)
        os.rename(src, dst)
        hist = actions.history()
        e = next(x for x in hist if x["id"] == "abc123")
        self.assertIn("interruption", e["note"])
        actions.undo("abc123")
        self.assertTrue(src.exists())

    def test_a_pending_move_that_never_happened_is_dropped(self):
        d = self.scratch("never")
        src = fixture.write(d / "x.txt", b"x")
        entry = {"id": "neverdone", "op": "move", "src": str(src), "dst": str(d / "out" / "x.txt"), "note": ""}
        with open(config.app_dir() / "journal.jsonl", "a") as f:
            f.write(json.dumps({"pending": entry}) + "\n")
        self.assertFalse(any(x["id"] == "neverdone" for x in actions.history()))
        self.assertFalse((config.app_dir() / "journal.jsonl").exists())

    def test_interrupted_batch_can_be_finished(self):
        d = self.scratch("interrupted")
        files = [fixture.write(d / f"g{i}.txt", b"x") for i in range(3)]
        planned = [{"path": str(f), "action": "move", "dest": str(d / "out"), "note": ""} for f in files]
        start = actions._log({"op": "batch", "label": "Stopped", "items": planned})
        actions.move(files[0], d / "out", self.cfg, batch=start["id"])  # one done, then the app quit
        stopped = [b for b in actions.interrupted_batches() if b["id"] == start["id"]]
        self.assertEqual((stopped[0]["done"], stopped[0]["planned"]), (1, 3))
        res = actions.resume_batch(start["id"], self.cfg)
        self.assertEqual(len(res), 2)
        self.assertTrue(all((d / "out" / f.name).exists() for f in files))
        self.assertFalse(any(b["id"] == start["id"] for b in actions.interrupted_batches()))


class PreMoveTests(Organise):
    def test_projects_wait_while_live_is_open(self):
        d = self.scratch("live")
        proj = fixture.project(d, "Busy Project", samples=["a.wav"])
        safety.app_running = lambda p: p == "Live"
        try:
            res = actions.apply([{"path": str(proj), "action": "move", "dest": str(d / "out")}], self.cfg)
            self.assertFalse(res[0]["ok"])
            self.assertIn("Live is open", res[0]["error"])
            other = fixture.write(d / "notes.txt", b"n")  # not Live's: unaffected
            self.assertTrue(actions.apply([{"path": str(other), "action": "move", "dest": str(d / "out")}], self.cfg)[0]["ok"])
        finally:
            safety.app_running = lambda p: False
        self.assertTrue(proj.exists())

    def test_different_disk_is_refused(self):
        d = self.scratch("disk")
        f = fixture.write(d / "x.txt", b"x")
        real = safety.same_disk
        safety.same_disk = lambda a, b: False
        try:
            res = actions.apply([{"path": str(f), "action": "move", "dest": str(d / "out")}], self.cfg)
        finally:
            safety.same_disk = real
        self.assertIn("different disk", res[0]["error"])
        self.assertTrue(f.exists())

    def test_icloud_only_files_never_leave_icloud(self):
        inside = self.cloud / "Scratch"
        f = fixture.write(inside / "cloudy.wav", b"x")
        real = safety.cloud_only
        safety.cloud_only = lambda p: True
        try:
            out = actions.apply([{"path": str(f), "action": "move", "dest": str(self.home / "Scratch" / "out")}], self.cfg)
            self.assertIn("only in iCloud", out[0]["error"])
            gone = actions.apply([{"path": str(f), "action": "trash"}], self.cfg)  # the Trash is outside iCloud too
            self.assertIn("only in iCloud", gone[0]["error"])
            within = actions.apply([{"path": str(f), "action": "move", "dest": str(inside / "sub")}], self.cfg)
            self.assertTrue(within[0]["ok"], within)  # a rename inside iCloud is fine
        finally:
            safety.cloud_only = real

    def test_cloud_only_flag_is_read_from_the_file(self):
        d = self.scratch("flags")
        f = fixture.write(d / "x.wav", b"x")
        self.assertFalse(safety.cloud_only(str(f)))
        fixture.write(d / ".y.wav.icloud", b"placeholder")
        self.assertTrue(safety.cloud_only(str(d)))

    def test_moved_sets_are_checked_again(self):
        d = self.scratch("verify")
        proj = fixture.project(d, "Check Project", samples=["a.wav"])
        als = proj / "Check.als"
        dbfile = d / "v.db"
        con = db.connect(dbfile)
        con.execute("INSERT INTO ableton_sets VALUES (?,?,?,?,?,?,?,?,?,?)", (str(als), str(proj), "", 1, 1, 0, 0, 0, "{}", None))
        con.commit()
        ok = actions.apply([{"path": str(proj), "action": "move", "dest": str(d / "moved")}], self.cfg)
        self.assertEqual(ableton.verify_moves(con, ok), [])  # self-contained: still fine
        moved_proj = d / "moved" / "Check Project"
        shutil.rmtree(moved_proj / "Samples")  # pretend the move lost its samples
        problems = ableton.verify_moves(con, ok)
        self.assertEqual((problems[0]["missing_before"], problems[0]["missing_after"]), (0, 1))
        self.assertEqual(problems[0]["batch"], ok[0]["batch"])
        con.close()

    def test_backup_reminder(self):
        real = backup._from_tmutil
        backup._cache.clear()
        try:
            backup._from_tmutil = lambda: time.time() - 30 * 86400
            st = backup.status()
            if st["supported"]:
                self.assertTrue(st["remind"])
                self.assertAlmostEqual(st["days"], 30, delta=0.1)
            backup._cache.clear()
            backup._from_tmutil = lambda: time.time() - 3600
            if backup.status()["supported"]:
                self.assertFalse(backup.status()["remind"])
        finally:
            backup._from_tmutil = real
            backup._cache.clear()


class LibraryTests(Organise):
    def test_set_up_library(self):
        root = self.cloud / "Active Storage"
        cfg = config.set_up_library(self.cfg, str(root), ["Active", "Dormant", "Finished", "Archive"])
        self.assertEqual(cfg["library_root"], "{cloud}/Active Storage")
        lib = config.library_paths(cfg)
        self.assertEqual(lib["statuses"]["Finished"], str(root / "Projects" / "Finished"))
        self.assertEqual(str(config.expand("{ableton}", cfg)), str(root / "Projects"))
        self.assertEqual(cfg["ableton_buckets"], ["Active", "Dormant", "Finished", "Archive"])
        self.assertIn("main folder", safety.protected_reason(str(root / "Projects"), cfg) or "")
        rules = {r["name"]: r for r in cfg["rules"]}
        self.assertEqual(rules["Loose Ableton sets"]["dest"], "{ableton}/Active")  # there's no Ideas folder now
        self.assertEqual(rules["Ableton projects"]["dest"], "{ableton}/Active")
        with self.assertRaises(ValueError):
            config.set_up_library(self.cfg, "/tmp", None)
        with self.assertRaises(ValueError):
            config.set_up_library(self.cfg, str(root), ["bad/name"])

    def test_before_setup_projects_use_the_ableton_folders(self):
        lib = config.library_paths(self.cfg)
        self.assertFalse(lib["ready"])
        self.assertEqual(lib["projects"], str(self.cloud / "Ableton Projects"))
        self.assertIn("Ideas", lib["statuses"])

    def test_school_and_money_rules(self):
        items = {i["name"]: i for ib in inbox.list_inboxes(self.cfg)["inboxes"] for i in ib["items"]}
        self.assertEqual(items["ENG101 essay.pdf"]["suggestion"]["rule"], "School")
        self.assertEqual(items["2025 taxes.pdf"]["suggestion"]["rule"], "Money")
        self.assertNotEqual(items["Kick 128.wav"]["suggestion"]["rule"], "School")

    def test_saved_settings_upgrade_keeps_edits(self):
        saved = [{"name": "Documents", "when": {"category": ["document"]}, "action": "move", "dest": "~/MyDocs"},
                 {"name": "Mine", "when": {"ext": [".x"]}, "action": "move", "dest": "~/X"}]
        rules = {r["name"]: r for r in config.migrate_rules(saved)}
        self.assertEqual(rules["Documents"]["dest"], "~/MyDocs")
        self.assertIn("School", rules)
        self.assertIn("Mine", rules)


class ExportTests(Organise):
    def idx(self):
        return exports.index(self.con)

    def group(self, folder):
        return self.idx().group_for_folder(str(folder))

    def test_kinds(self):
        self.assertEqual(exports.audio_kind("Song (MASTER 24-bit 48k).wav"), "master")
        self.assertEqual(exports.audio_kind("Fixing (24bit48k premaster).wav"), "master")
        self.assertEqual(exports.audio_kind("Blackout Remix V10.wav"), "bounce")
        self.assertEqual(exports.audio_kind("vocal chop.wav"), "other")

    def test_track_names_are_read(self):
        rows = self.con.execute("SELECT name, kind FROM ableton_tracks WHERE set_path=? ORDER BY position",
                                (str(self.nightdrive / "Night Drive Remix.als"),)).fetchall()
        self.assertEqual([r["name"] for r in rows], ["Drums", "Bass", "Lead Synth", "Vox", "A-Reverb"])
        self.assertEqual(rows[-1]["kind"], "return")

    def test_stem_group_matched_by_name_and_tracks(self):
        g = self.group(self.home / "Downloads" / "Night Drive Remix Stems")
        self.assertEqual(g["prefix"], "Night Drive Remix")
        self.assertEqual(g["tracks"], ["Bass", "Drums", "Lead Synth", "Vox"])
        self.assertTrue(g["mix"].endswith("Night Drive Remix.wav"))
        self.assertEqual((g["project"], g["confidence"]), (str(self.nightdrive), "sure"))

    def test_stem_group_matched_by_tracks_only(self):
        g = self.group(self.home / "Desktop" / "Export Dump")
        self.assertEqual((g["project"], g["confidence"]), (str(self.nightdrive), "likely"))
        self.assertIn("track names", g["why"])

    def test_stem_prep_record_makes_it_sure(self):
        g = self.group(self.home / "Downloads" / "stemprep export")
        self.assertEqual(g["project"], str(self.songz))
        self.assertEqual(g["confidence"], "sure")
        self.assertEqual(g["stem_prep"]["song"], "Song Z")

    def test_sample_packs_and_project_ingredients_are_not_stems(self):
        self.assertIsNone(self.group(self.home / "Downloads" / "Drum Pack Vol 2"))
        self.assertFalse(any("/Samples/" in g["folder"] for g in self.idx().groups))

    def test_unmatched_stems_have_no_project(self):
        g = self.group(self.home / "Downloads" / "Mystery Stems")
        self.assertIsNone(g["project"])

    def test_checklist(self):
        data = server.api_ableton({})
        by = {p["path"]: p for p in data["projects"]}
        tidy = by[str(self.tidy)]["checklist"]
        self.assertEqual((tidy["self_contained"], tidy["master"], tidy["stems"], tidy["organised"]), (True, "in", "in", True))
        ni = by[str(self.nightdrive)]
        self.assertEqual(ni["checklist"]["stems"], "elsewhere")
        self.assertEqual(len(ni["stem_groups"]), 2)
        self.assertFalse(data["tracks_rescan_needed"])
        self.assertTrue(any(g["prefix"] == "Who Knows" for g in data["exports"]["unmatched_groups"]))
        marks.set_flag(str(self.songz), "no_master", True)
        try:
            exports._cache.clear()
            sz = {p["path"]: p for p in server.api_ableton({})["projects"]}[str(self.songz)]
            self.assertEqual(sz["checklist"]["master"], "not-needed")
        finally:
            marks.set_flag(str(self.songz), "no_master", False)

    def test_live_pins_and_template(self):
        pins = live_prefs.pinned_folders()
        self.assertIn(str(self.cloud / "Active Storage"), pins)
        self.assertTrue(live_prefs.template_problem().endswith("Default.als"))


class PlanTests(Organise):
    def plan(self, folder, cfg=None):
        return plan.plan_folder(self.con, cfg or self.cfg, str(folder))

    def by_name(self, data):
        return {p["name"]: p for p in data["items"]}

    def test_downloads(self):
        items = self.by_name(self.plan(self.home / "Downloads"))
        stems_folder = items["Night Drive Remix Stems"]
        self.assertEqual(stems_folder["dest"], str(self.nightdrive / "Exports" / "Stems"))
        self.assertEqual(stems_folder["confidence"], "sure")
        self.assertTrue(stems_folder["ticked"])
        loose = items["Loose Tune Drums.wav"]
        self.assertEqual(loose["dest"], str(self.loose / "Exports" / "Stems" / "Loose Tune"))
        master = items["Night Drive Remix (MASTER).wav"]
        self.assertEqual(master["dest"], str(self.nightdrive / "Exports" / "Master"))
        self.assertEqual(items["Night Drive Remix V10.wav"]["dest"], str(self.nightdrive / "Exports" / "Bounces"))
        older = items["Night Drive Remix V2.wav"]
        self.assertEqual(older["dest"], str(self.nightdrive / "Exports" / "Bounces" / "Older versions"))
        self.assertIn("older bounce of Night Drive Remix (v2; the newest is v10)", older["reason"])
        self.assertEqual(items["ENG101 essay.pdf"]["confidence"], "guess")
        self.assertFalse(items["ENG101 essay.pdf"]["ticked"])  # guesses never start ticked
        mystery = items["Mystery Stems"]
        self.assertTrue(any("might be a stem export" in w for w in mystery["warnings"]))

    def test_projects_get_a_status_and_blockers(self):
        cfg = config.set_up_library(self.cfg, str(self.cloud / "Active Storage"), ["Active", "Dormant", "Finished", "Archive"])
        items = self.by_name(self.plan(self.nightdrive.parent, cfg))
        ni = items["Night Drive Remix Project"]
        self.assertEqual(ni["dest"], str(self.cloud / "Active Storage" / "Projects" / "Finished"))
        self.assertEqual(ni["confidence"], "likely")
        old = self.by_name(self.plan(self.home / "Downloads", cfg))["Old Song Project"]
        self.assertTrue(any("Collect All" in b for b in old["blockers"]))
        self.assertFalse(old["ticked"])

    def test_used_and_protected_things_stay(self):
        items = self.by_name(self.plan(self.home / "Downloads"))
        self.assertEqual(items["bass one-shot.wav"]["action"], "keep")  # a preset in the User Library uses it
        self.assertTrue(items["bass one-shot.wav"]["blockers"])

    def test_pinned_folders_warn(self):
        items = self.by_name(self.plan(self.home / "Desktop"))
        asym = items.get("ASYM Music")
        if asym and asym["action"] == "move":
            self.assertTrue(any("Live's browser" in w for w in asym["warnings"]))

    def test_folders_that_cant_be_planned(self):
        h = self.home
        self.assertIn("Library", plan.folder_problem(str(h / "Library" / "Caches"), self.cfg))
        self.assertIn("rekordbox", plan.folder_problem(str(self.cloud / "Active Storage" / "rekordbox"), self.cfg))
        self.assertIn("inside an Ableton project", plan.folder_problem(str(self.nightdrive / "Samples"), self.cfg))
        self.assertIn("User Library", plan.folder_problem(str(self.cloud / "Active Storage" / "User Library"), self.cfg))
        self.assertIsNone(plan.folder_problem(str(h / "Downloads"), self.cfg))
        self.assertIn("error", self.plan(h / "Library" / "Caches"))

    def test_decisions_are_saved(self):
        folder = str(self.home / "Desktop")
        plan.save_decisions(folder, {"/x/y.wav": {"action": "move", "dest": "~/Z", "ticked": True}, "/bad": {"action": "nuke"}})
        saved = self.plan(folder)["decisions"]
        self.assertEqual(saved, {"/x/y.wav": {"action": "move", "dest": "~/Z", "ticked": True}})

    def test_preview_changes_nothing_and_runs_every_check(self):
        d = self.scratch("preview")
        proj = fixture.project(d, "Preview Project", samples=["a.wav"])
        f = fixture.write(d / "file.txt", b"x")
        safety.app_running = lambda p: p == "Live"
        try:
            res = plan.preview([{"path": str(f), "action": "move", "dest": str(d / "out")},
                                {"path": str(proj), "action": "move", "dest": str(d / "out")},
                                {"path": str(f), "action": "keep"}], self.cfg)
        finally:
            safety.app_running = lambda p: False
        self.assertEqual(len(res), 2)
        self.assertTrue(res[0]["ok"] and res[0]["dry_run"])
        self.assertIn("Live is open", res[1]["error"])
        self.assertTrue(f.exists() and proj.exists())
        self.assertFalse((d / "out").exists())
        self.assertFalse(any(b["label"] for b in actions.batches() if b["planned"] == 2 and "preview" in b["label"]))

    def test_plan_endpoint(self):
        out = server.api_plan({"folder": [str(self.home / "Downloads")]})
        self.assertTrue(out["items"])
        self.assertTrue(any(p["label"] == "Downloads" for p in out["places"]))
        self.assertIn("suggestions", out["setup"])


class TagTests(Organise):
    def setUp(self):
        for d in marks.tag_defs():
            marks.delete_tag(d["name"])

    def test_create_and_refuse_duplicates(self):
        t = marks.create_tag("Forever", "Album / EP")
        self.assertEqual((t["name"], t["kind"]), ("Forever", "Album / EP"))
        with self.assertRaises(ValueError):
            marks.create_tag("forever")  # names ignore case
        with self.assertRaises(ValueError):
            marks.create_tag("   ")
        with self.assertRaises(ValueError):
            marks.create_tag("x" * 41)

    def test_tag_projects_and_filter_data(self):
        marks.create_tag("Forever", "Album / EP")
        p1, p2 = str(self.nightdrive), str(self.songz)
        self.assertEqual(marks.set_tags(p1, ["forever", "Remix"]), ["Forever", "Remix"])  # stored spelling; new ones made
        self.assertEqual(marks.tag_defs()[-1], {"name": "Remix", "kind": "Other", "color": 2})
        marks.add_tags([p1, p2], ["Collab"])
        data = server.api_ableton({})
        by = {p["path"]: p for p in data["projects"]}
        self.assertEqual(by[p1]["tags"], ["Forever", "Remix", "Collab"])
        self.assertEqual(by[p2]["tags"], ["Collab"])
        self.assertEqual([d["name"] for d in data["tag_defs"]], ["Forever", "Remix", "Collab"])
        self.assertIn("Album / EP", data["tag_kinds"])
        self.assertEqual(marks.set_tags(p2, []), [])
        self.assertEqual({p["path"]: p for p in server.api_ableton({})["projects"]}[p2]["tags"], [])

    def test_rename_and_delete_everywhere(self):
        p1 = str(self.nightdrive)
        marks.set_tags(p1, ["Forevr", "Remix"])
        marks.update_tag("Forevr", new_name="Forever", kind="Album / EP", color=3)
        self.assertEqual(marks.tags_for(p1, marks.tags_lookup()), ["Forever", "Remix"])
        self.assertEqual(next(d for d in marks.tag_defs() if d["name"] == "Forever")["color"], 3)
        with self.assertRaises(ValueError):
            marks.update_tag("Forever", new_name="remix")
        marks.delete_tag("Remix")
        self.assertEqual(marks.tags_for(p1, marks.tags_lookup()), ["Forever"])
        self.assertNotIn("Remix", [d["name"] for d in marks.tag_defs()])

    def test_tags_follow_moves(self):
        d = self.scratch("tagmove")
        proj = fixture.project(d, "Tagged Project", samples=["a.wav"])
        marks.set_tags(str(proj), ["Forever"])
        res = actions.apply([{"path": str(proj), "action": "move", "dest": str(d / "moved")}], self.cfg)
        moved = d / "moved" / "Tagged Project"
        self.assertEqual(marks.tags_for(str(moved), marks.tags_lookup()), ["Forever"])
        actions.undo_batch(res[0]["batch"])
        self.assertEqual(marks.tags_for(str(proj), marks.tags_lookup()), ["Forever"])
        # moved in Finder: found again by folder name
        self.assertEqual(marks.tags_for("/somewhere/else/Tagged Project", marks.tags_lookup()), ["Forever"])

    def test_endpoints(self):
        self.assertFalse(server.post_ableton_tags({"path": "relative"})["ok"])
        self.assertFalse(server.post_ableton_tags({"paths": []})["ok"])
        self.assertTrue(server.post_tag({"op": "create", "name": "Sketch", "kind": "Type"})["ok"])
        self.assertFalse(server.post_tag({"op": "create", "name": "sketch"})["ok"])
        self.assertTrue(server.post_ableton_tags({"path": str(self.tidy), "tags": ["Sketch"]})["ok"])
        self.assertTrue(server.post_tag({"op": "update", "name": "Sketch", "new_name": "Idea"})["ok"])
        self.assertEqual(marks.tags_for(str(self.tidy), marks.tags_lookup()), ["Idea"])
        self.assertTrue(server.post_tag({"op": "delete", "name": "Idea"})["ok"])
        self.assertFalse(server.post_tag({"op": "explode"})["ok"])


class BrokenProjectTests(Organise):
    def setUp(self):
        for flag in ("archive_broken", "move_anyway"):
            for path in marks.flagged(flag):
                marks.set_flag(path, flag, False)

    def broken(self, name):
        d = self.scratch(name)
        outside = fixture.write(d / "outside" / "kick.wav", size=10_000)
        proj = fixture.project(d, f"{name} Project", samples=["a.wav"], external=[outside], missing=["gone.wav"])
        return d, proj

    def test_projects_with_outside_files_stay_put(self):
        d, proj = self.broken("Old")
        res = actions.apply([{"path": str(proj), "action": "move", "dest": str(d / "moved")}], self.cfg)
        self.assertFalse(res[0]["ok"])
        self.assertIn("outside its folder", res[0]["error"])
        self.assertIn("missing", res[0]["error"])
        self.assertTrue(proj.exists())
        # a folder holding it can't sneak it out either
        res = actions.apply([{"path": str(d), "action": "move", "dest": str(self.home / "Scratch" / "elsewhere")}], self.cfg)
        self.assertFalse(res[0]["ok"])
        # nor can a preview pretend it would work
        self.assertFalse(plan.preview([{"path": str(proj), "action": "move", "dest": str(d / "moved")}], self.cfg)[0]["ok"])

    def test_loose_set_with_outside_files_stays_put(self):
        d = self.scratch("loose-set")
        outside = fixture.write(self.scratch("elsewhere") / "snare.wav", size=10_000)
        als = fixture.write(d / "sets" / "Loose.als", fixture.als_xml([(str(outside), "")]))
        res = actions.apply([{"path": str(als), "action": "move", "dest": str(d / "moved")}], self.cfg)
        self.assertFalse(res[0]["ok"])

    def test_marked_projects_may_move_and_undo_always_works(self):
        for flag in ("archive_broken", "move_anyway"):
            d, proj = self.broken("Marked " + flag)
            marks.set_flag(str(proj), flag, True)
            res = actions.apply([{"path": str(proj), "action": "move", "dest": str(d / "moved")}], self.cfg)
            self.assertTrue(res[0]["ok"], res)
            moved = d / "moved" / proj.name
            self.assertIn(str(moved), marks.flagged(flag))  # the mark moved with it
            marks.set_flag(str(moved), flag, False)
            self.assertEqual(actions.undo_batch(res[0]["batch"])["undone"], 1)  # putting back is never blocked
            self.assertTrue(proj.exists())

    def test_self_contained_projects_move_freely(self):
        d = self.scratch("fine")
        proj = fixture.project(d, "Fine Project", samples=["a.wav"])
        self.assertTrue(actions.apply([{"path": str(proj), "action": "move", "dest": str(d / "moved")}], self.cfg)[0]["ok"])

    def test_overview_and_plan(self):
        old = self.home / "Downloads" / "Old Song Project"  # the fixture's project with an outside sample
        marks.set_flag(str(old), "archive_broken", True)
        data = server.api_ableton({})
        p = {x["path"]: x for x in data["projects"]}[str(old)]
        self.assertTrue(p["archivable"])
        self.assertFalse(p["in_broken"])
        self.assertTrue(data["broken_dir"].endswith("Broken Projects"))
        item = {i["name"]: i for i in plan.plan_folder(self.con, self.cfg, str(self.home / "Downloads"))["items"]}["Old Song Project"]
        self.assertEqual((item["dest"], item["confidence"], item["blockers"], item["ticked"]),
                         (data["broken_dir"], "sure", [], True))
        marks.set_flag(str(old), "archive_broken", False)
        marks.set_flag(str(old), "move_anyway", True)
        item = {i["name"]: i for i in plan.plan_folder(self.con, self.cfg, str(self.home / "Downloads"))["items"]}["Old Song Project"]
        self.assertEqual(item["blockers"], [])
        self.assertTrue(any("allowed moving it anyway" in w for w in item["warnings"]))
        self.assertIn("main folder", safety.protected_reason(data["broken_dir"], self.cfg) or "")

    def test_flag_endpoint(self):
        self.assertFalse(server.post_ableton_flag({"path": str(self.tidy), "flag": "delete_everything", "on": True})["ok"])
        self.assertTrue(server.post_ableton_flag({"path": str(self.tidy), "flag": "archive_broken", "on": True})["ok"])
        self.assertIn(str(self.tidy), marks.flagged("archive_broken"))


class UserLibraryTests(Organise):
    def test_user_library_is_not_a_project(self):
        ul = self.cloud / "Active Storage" / "User Library"
        fixture.write(ul / "Ableton Project Info" / "Project8_1.cfg", b"cfg")  # Live puts one there
        fixture.write(ul / "Templates" / "Default.als", fixture.als_xml([]))
        from macclean import classify
        self.assertFalse(classify.is_ableton_project(str(ul)))
        tmp = Path(tempfile.mkdtemp())
        try:
            dbfile = tmp / "s.db"
            con = db.connect(dbfile)  # a scan made before this change marked it as a project
            con.execute("INSERT INTO dirs VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (str(ul), str(ul.parent), "User Library", 9, 1, 1, 1, 0, "ableton-project", "user"))
            con.commit()
            self.assertEqual([r[0] for r in con.execute("SELECT path FROM dirs WHERE " + db.PROJECTS)], [])
            con.close()
        finally:
            shutil.rmtree(tmp)
        Scanner(self.cfg).run()
        con = db.connect()
        try:
            kinds = {r["path"]: r["kind"] for r in con.execute("SELECT path, kind FROM dirs WHERE name='User Library'")}
            self.assertNotIn("ableton-project", kinds.values())
            data = ableton.overview(con, self.cfg)
            self.assertFalse(any(p["name"] == "User Library" for p in data["projects"]))
            self.assertFalse(any("/User Library/" in s["path"] for s in data["loose_sets"]))  # templates aren't loose sets
            self.assertTrue(any(s["path"].endswith("Beat idea.als") for s in data["loose_sets"]))  # real loose sets still are
        finally:
            con.close()
            exports._cache.clear()


class NewestSetTests(Organise):
    def project_with_versions(self, name, newest_ok):
        d = self.scratch(name)
        outside = fixture.write(self.scratch(name + "-outside") / "loop.wav", size=10_000)
        proj = fixture.project(d, f"{name} Project", samples=["a.wav"])
        inside = proj / "Samples" / "Imported" / "a.wav"
        good = fixture.als_xml([(str(inside), "Samples/Imported/a.wav")])
        bad = fixture.als_xml([(str(outside), "")])
        fixture.write(proj / f"{name} old.als", good if not newest_ok else bad, age_days=30)
        fixture.write(proj / f"{name} new.als", good if newest_ok else bad, age_days=0)
        (proj / f"{name}.als").unlink()  # the helper's own set: leave just the two versions
        return d, proj

    def test_old_uncollected_versions_dont_stop_a_move(self):
        d, proj = self.project_with_versions("Versions", newest_ok=True)
        res = actions.apply([{"path": str(proj), "action": "move", "dest": str(d / "moved")}], self.cfg)
        self.assertTrue(res[0]["ok"], res)

    def test_an_uncollected_newest_set_does(self):
        d, proj = self.project_with_versions("Latest", newest_ok=False)
        res = actions.apply([{"path": str(proj), "action": "move", "dest": str(d / "moved")}], self.cfg)
        self.assertFalse(res[0]["ok"])
        self.assertIn("newest set", res[0]["error"])

    def test_overview_and_plan_use_the_newest_set(self):
        remix = self.cloud / "Ableton Projects" / "Remix Project"  # newest set fine, an older one isn't
        p = {x["path"]: x for x in server.api_ableton({})["projects"]}[str(remix)]
        self.assertEqual(p["status"], "missing")  # still listed in Collect All
        self.assertTrue(p["movable"])
        self.assertTrue(p["checklist"]["self_contained"])
        item = {i["name"]: i for i in plan.plan_folder(self.con, self.cfg, str(remix.parent))["items"]}["Remix Project"]
        self.assertEqual(item["blockers"], [])
        self.assertTrue(any("older set" in w for w in item["warnings"]))
        song_b = {i["name"]: i for i in plan.plan_folder(self.con, self.cfg, str(remix.parent))["items"]}["Song B Project"]
        self.assertTrue(any("newest set" in b for b in song_b["blockers"]))


class StableLibraryTests(Organise):
    def test_user_library_samples_dont_stop_a_move(self):
        d = self.scratch("ulib")
        ul = self.cloud / "Active Storage" / "User Library" / "Samples" / "lib kick.wav"
        fixture.write(ul, size=20_000)
        proj = fixture.project(d, "Lib User Project", samples=["a.wav"], external=[ul])
        res = actions.apply([{"path": str(proj), "action": "move", "dest": str(d / "moved")}], self.cfg)
        self.assertTrue(res[0]["ok"], res)
        loose = fixture.write(self.scratch("ulib-outside") / "stray.wav", size=20_000)
        proj2 = fixture.project(d, "Stray Project", samples=["a.wav"], external=[ul, loose])
        res = actions.apply([{"path": str(proj2), "action": "move", "dest": str(d / "moved")}], self.cfg)
        self.assertFalse(res[0]["ok"])
        self.assertIn("uses 1 file outside", res[0]["error"])  # the User Library one doesn't count

    def test_stable_count_from_old_scans(self):
        self.assertEqual(ableton.stable_outside({"external": 2, "examples": {"external": [
            "/x/User Library/Samples/a.wav", "/x/Downloads/b.wav"]}}), 1)
        self.assertEqual(ableton.stable_outside({"external": 20, "examples": {"external": ["/x/User Library/a.wav"]}}), 0)


class OtherAppsTests(Organise):
    def test_rekordbox_tracks_stay_put(self):
        from macclean import links
        cfg = dict(self.cfg, rekordbox_xml="~/Documents/rekordbox.xml")
        self.assertEqual(links.rekordbox_tracks(str(self.home / "Documents" / "rekordbox.xml")), [str(self.dj_track)])
        used = safety.UsedIndex(self.con, cfg)
        self.assertEqual(used.users(str(self.dj_track)), ["rekordbox"])
        self.assertIn("rekordbox", safety.preflight(used, str(self.dj_track), "move"))
        item = {i["name"]: i for i in plan.plan_folder(self.con, cfg, str(self.home / "Downloads"))["items"]}["Club Edit.aif"]
        self.assertEqual(item["action"], "keep")
        self.assertEqual(item["blockers"], ["used by rekordbox"])
        self.assertIsNone(safety.UsedIndex(self.con, self.cfg).users(str(self.dj_track)) or None)  # not set: not protected

    def test_bad_rekordbox_file(self):
        from macclean import links
        bad = fixture.write(self.scratch("rb") / "nope.xml", b"<html>")
        st = links.rekordbox_status(dict(self.cfg, rekordbox_xml=str(bad)))
        self.assertTrue(st["error"])
        self.assertFalse(server.post_links({"rekordbox_xml": str(bad)})["ok"])
        self.assertFalse(server.post_links({"rekordbox_xml": "/no/such/file.xml"})["ok"])

    def test_final_cut_links(self):
        from macclean import links
        self.assertEqual(links.fcp_links(self.con), {str(self.video): "Videos.fcpbundle"})
        used = safety.UsedIndex(self.con, self.cfg)
        self.assertEqual(used.users(str(self.video)), ["the Final Cut library “Videos”"])
        st = links.status(self.con, self.cfg)
        self.assertEqual((st["final_cut"]["links"], st["final_cut"]["library_names"]), (1, ["Videos"]))
        items = {i["name"]: i for ib in inbox.list_inboxes(self.cfg)["inboxes"] for i in ib["items"]}
        data = {"inboxes": [{"items": [items["music video.mov"]]}]}
        inbox.mark_used_by_sets(data, self.con, self.cfg)
        self.assertEqual(items["music video.mov"]["suggestion"]["action"], "keep")
        self.assertIn("Final Cut", items["music video.mov"]["used_by_text"])


class MissingTests(Organise):
    def test_find_missing(self):
        from macclean import missing
        r = missing.find_for_project(self.con, str(self.lost))
        self.assertEqual((r["missing"], r["findable"], r["gone"]), (3, 2, 1))
        self.assertEqual(r["folders"][0], {"folder": str(self.cloud / "Active Storage" / "Sample Stash"), "covers": 2})
        items = {i["name"]: i for i in r["sets"][0]["items"]}
        self.assertIn("Google Drive", items["vocal.wav"]["gone"])
        self.assertTrue(items["pad.wav"]["candidates"][0].endswith("Keys/pad.wav"))
        self.assertTrue(r["sets"][0]["newest"])
        self.assertIn("error", server.api_ableton_missing({"project": ["/not/a/project"]}))

    def test_why_gone(self):
        from macclean import missing
        self.assertIn("older Mac", missing.why_gone("/Users/somebodyelse/Samples/x.wav"))
        self.assertIn("isn't connected", missing.why_gone("/Volumes/No Such Drive 12345/x.wav"))
        self.assertIsNone(missing.why_gone(str(self.home / "Music" / "x.wav")))

    def test_mark_many_as_broken(self):
        paths = [str(self.lost), str(self.songz)]
        self.assertEqual(server.post_ableton_flag({"paths": paths, "flag": "archive_broken", "on": True})["count"], 2)
        self.assertTrue(set(paths) <= marks.flagged("archive_broken"))
        server.post_ableton_flag({"paths": paths, "flag": "archive_broken", "on": False})
        self.assertFalse(set(paths) & marks.flagged("archive_broken"))


class ReceivedStemsTests(Organise):
    def idx(self):
        return exports.index(self.con)

    def test_tracks_named_after_the_files(self):
        g = self.idx().group_for_folder(str(self.home / "Downloads" / "Harbor Parts"))
        self.assertEqual((g["project"], g["received"]), (str(self.harbor), True))
        self.assertIn("named after these files", g["why"])
        items = {p["name"]: p for p in plan.plan_folder(self.con, self.cfg, str(self.home / "Downloads"))["items"]}
        self.assertEqual(items["Harbor Parts"]["dest"], str(self.harbor / "Samples" / "Received Stems"))
        self.assertEqual(items["Harbor Parts"]["rule"], "Received stems → project")

    def test_collected_into_the_project_is_a_copy(self):
        g = self.idx().group_for_folder(str(self.home / "Downloads" / "Sent Parts"))
        self.assertEqual((g["project"], g["received"]), (str(self.cover), True))
        self.assertIn("use them as samples", g["why"])
        self.assertEqual(g["copy_of"], str(self.cover / "Samples" / "Imported"))
        item = {p["name"]: p for p in plan.plan_folder(self.con, self.cfg, str(self.home / "Downloads"))["items"]}["Sent Parts"]
        self.assertEqual((item["action"], item["ticked"]), ("trash", False))
        self.assertIn("Cover Song/Samples/Imported (checked: the files are identical)", item["reason"])

    def test_copy_of_filed_stems(self):
        item = {p["name"]: p for p in plan.plan_folder(self.con, self.cfg, str(self.home / "Desktop"))["items"]}["Tidy stems copy"]
        self.assertEqual((item["action"], item["ticked"], item["confidence"]), ("trash", False, "likely"))
        self.assertIn("Tidy/Exports/Stems/2026-10-01 Tidy", item["reason"])

    def test_older_than_the_project(self):
        g = self.idx().group_for_folder(str(self.home / "Downloads" / "Old Remix Pack"))
        self.assertEqual((g["project"], g["received"]), (str(self.oldremix), True))
        self.assertRegex(g["why"], r"(389|390) days before the project was started")

    def test_received_stems_dont_count_for_the_checklist(self):
        by = {p["path"]: p for p in server.api_ableton({})["projects"]}
        self.assertEqual(by[str(self.harbor)]["checklist"]["stems"], "none")
        self.assertTrue(by[str(self.harbor)]["stem_groups"][0]["received"])

    def test_exports_are_not_received(self):
        for folder in ("Night Drive Remix Stems", "stemprep export"):
            self.assertFalse(self.idx().group_for_folder(str(self.home / "Downloads" / folder))["received"])
        self.assertFalse(self.idx().group_for_folder(str(self.home / "Desktop" / "Export Dump"))["received"])


class ICloudTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.tmp)

    def tearDown(self):
        os.environ["HOME"] = self._home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_counts_files_only_in_icloud(self):
        import sqlite3
        from macclean import icloud
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE files (path TEXT, size INTEGER, ext TEXT, category TEXT, dataless INTEGER)")
        h = str(self.tmp)
        con.executemany("INSERT INTO files VALUES (?,?,?,?,?)", [
            (h + "/Desktop/Song Project/Song.als", 100, ".als", "ableton", 1),
            (h + "/Desktop/Song Project/Samples/Imported/a.wav", 1000, ".wav", "audio", 1),
            (h + "/Desktop/Song Project/b.wav", 5, ".wav", "audio", 0),
            (h + "/Documents/Game/save.dat", 7000, ".dat", "other", 1)])
        projects = [{"path": h + "/Desktop/Song Project", "name": "Song Project", "important": True},
                    {"path": h + "/Desktop/Tidy Project", "name": "Tidy Project"}]
        icloud.attach(con, projects)
        self.assertEqual(projects[0]["cloud_only"], {"files": 2, "bytes": 1100, "sets": 1})
        self.assertIsNone(projects[1]["cloud_only"])
        self.assertIsNone(projects[0]["kept_by"])
        st = icloud.status(con, config.load_config(), projects)
        self.assertEqual((st["projects"], st["important"], st["cloud_only_files"]), (1, ["Song Project"], 3))
        self.assertIn(st["optimise"], (True, False, None))
        # Music first, then the biggest.
        self.assertEqual([(a["path"], a["files"], a["music"]) for a in st["areas"]],
                         [(h + "/Desktop/Song Project", 2, True), (h + "/Documents/Game", 1, False)])

    def test_keep_downloaded_only_where_icloud_syncs(self):
        from macclean import icloud
        folder = self.tmp / "Music"
        folder.mkdir()
        with self.assertRaisesRegex(ValueError, "isn't synced with iCloud"):
            icloud.keep_downloaded(str(folder), True)
        with self.assertRaisesRegex(ValueError, "isn't there"):
            icloud.keep_downloaded(str(self.tmp / "nope"), True)
        self.assertFalse(server.post_icloud_keep({"path": "/usr", "on": True})["ok"])
        self.assertFalse(icloud.is_kept(str(folder)))

    def test_download_now(self):
        from macclean import icloud
        folder = self.tmp / "Desktop" / "Stems"
        fixture.write(folder / "a.wav", b"a" * 1234)
        fixture.write(folder / "b.wav", b"b" * 1234)
        fixture.write(folder / "here.wav", b"c" * 99)
        old = icloud._st_cloud_only
        icloud._st_cloud_only = lambda st: st.st_size == 1234  # pretend these two are only in iCloud
        try:
            job = server.post_icloud_download({"paths": [str(folder)], "label": "Stems"})["job"]
            self.assertEqual((job["files"], job["bytes"]), (2, 2468))
            for _ in range(100):
                done = [j for j in server.api_icloud_jobs({})["jobs"] if j["id"] == job["id"]][0]
                if done["finished"]:
                    break
                time.sleep(0.05)
            self.assertEqual((done["done"], done["errors"]), (2, []))
            real_disk = icloud.disk
            icloud.disk = lambda: {"free": 5e9, "total": 1e12, "low": True}
            try:
                r = server.post_icloud_download({"paths": [str(folder)]})
            finally:
                icloud.disk = real_disk
            self.assertFalse(r["ok"])
            self.assertIn("only 5.0 GB is free", r["error"])
        finally:
            icloud._st_cloud_only = old


class DataCopyTests(Organise):
    def test_mirror_then_restore_on_a_new_mac(self):
        from macclean import datacopy
        cfg = config.set_up_library(self.cfg, str(self.cloud / "Active Storage"), ["Active", "Dormant", "Finished", "Archive"])
        config.save_config(cfg)
        marks.create_tag("Forever", "Album / EP")
        marks.set_tags(str(self.songz), ["Forever"])
        d = Path(datacopy.mirror(cfg))
        self.assertEqual(d, self.cloud / "Active Storage" / "Mac Cleaner data")
        self.assertTrue((d / "marks.json").exists() and (d / "config.json").exists() and (d / "README.txt").exists())
        self.assertIsNone(datacopy.offer(cfg))  # this Mac has tags of its own
        # A new Mac, under another user name: nothing of Mac Cleaner's here yet.
        old = "/Users/someoneelse"
        about = json.loads((d / "about.json").read_text())
        about["home"] = old
        (d / "about.json").write_text(json.dumps(about))
        (d / "marks.json").write_text((d / "marks.json").read_text().replace(str(self.home), old))
        (config.app_dir() / "marks.json").unlink()
        (config.app_dir() / "config.json").unlink()
        o = datacopy.offer(config.load_config())  # found one level inside iCloud Drive
        self.assertEqual((o["path"], o["tagged"], o["tags"]), (str(d), 1, 1))
        r = server.post_data_copy_restore({"path": str(d)})
        self.assertTrue(r["ok"], r)
        self.assertEqual(marks.load()["tags"][str(self.songz)]["tags"], ["Forever"])  # under this Mac's home folder
        self.assertTrue(config.load_config()["library_ready"])
        self.assertFalse(server.post_data_copy_restore({"path": str(self.home)})["ok"])


class GuardTests(unittest.TestCase):
    def test_system_commands_are_stand_ins(self):
        for tool in guard.STAND_INS:
            self.assertTrue(shutil.which(tool).startswith(str(guard._bin)), tool)
        self.assertEqual(os.environ.get("MACCLEAN_SANDBOX"), "1")


if __name__ == "__main__":
    unittest.main()
