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
        fixture.write(h / "Downloads" / "ENG101 essay.pdf", b"%PDF-1.7 essay")
        fixture.write(h / "Downloads" / "2025 taxes.pdf", b"%PDF-1.7 taxes")
        fixture.write(h / "Downloads" / "Kick 128.wav", size=50_000, seed=3)
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


if __name__ == "__main__":
    unittest.main()
