import gzip
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture  # noqa: E402

from macclean import ableton, actions, config, db, inbox, purge, survey  # noqa: E402
from macclean.scanner import Scanner  # noqa: E402


class FakeHome(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.home = Path(cls.tmp) / "home"
        cls._old = {k: os.environ.get(k) for k in ("HOME", "MACCLEAN_HOME")}
        os.environ["HOME"] = str(cls.home)
        os.environ.pop("MACCLEAN_HOME", None)
        fixture.build(cls.home)
        cls.cfg = config.load_config()
        Scanner(cls.cfg).run()
        cls.con = db.connect()
        cls.cloud = cls.home / fixture.ICLOUD

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        for k, v in cls._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.tmp)


class ScanTests(FakeHome):
    def test_sizes_roll_up(self):
        home = self.con.execute("SELECT * FROM dirs WHERE path=?", (str(self.home),)).fetchone()
        kids = self.con.execute("SELECT SUM(alloc) FROM dirs WHERE parent=?", (str(self.home),)).fetchone()[0]
        self.assertGreater(home["alloc"], 30_000_000)
        self.assertLessEqual(kids, home["alloc"])

    def test_library_is_app_data_but_icloud_is_user_content(self):
        cats = {r["category"] for r in self.con.execute("SELECT category FROM files WHERE path LIKE ?",
                                                        (str(self.cloud) + "/%",))}
        self.assertNotIn("library", cats)
        blob = self.con.execute("SELECT category FROM files WHERE name='blob'").fetchone()
        self.assertEqual(blob["category"], "library")

    def test_ableton_projects_detected(self):
        n = self.con.execute("SELECT COUNT(*) FROM dirs WHERE kind='ableton-project'").fetchone()[0]
        self.assertEqual(n, 5)

    def test_duplicates_skip_ableton_project_contents(self):
        paths = [r["path"] for r in self.con.execute("SELECT path FROM dupes")]
        self.assertTrue(any(p.endswith("vocal chop.wav") for p in paths))
        self.assertFalse(any("Project/Samples" in p for p in paths), paths)


class AbletonTests(FakeHome):
    def test_parse_ignores_source_context(self):
        als = self.home / "Downloads" / "Old Song Project" / "Old Song.als"
        refs = ableton.parse_set(str(als))["refs"]
        self.assertEqual(len(refs), 2)
        self.assertFalse(any("never-there" in r["path"] for r in refs))

    def test_live9_relative_path_elements(self):
        proj = self.home / "Live9 Project"
        (proj / "Ableton Project Info").mkdir(parents=True)
        (proj / "Samples").mkdir()
        (proj / "Samples" / "a.wav").write_bytes(b"x")
        xml = ('<Ableton Creator="Ableton Live 9.7.7"><FileRef><RelativePath>'
               '<RelativePathElement Dir="Samples" /></RelativePath><Name Value="a.wav" /></FileRef></Ableton>')
        (proj / "s.als").write_bytes(gzip.compress(xml.encode()))
        res = ableton.check_set(str(proj / "s.als"), str(proj))
        self.assertEqual((res["in_project"], res["missing"], res["version"]), (1, 0, "Ableton Live 9.7.7"))

    def test_project_status(self):
        ov = ableton.overview(self.con, self.cfg)
        by_name = {(p["name"], p["in_library"]): p for p in ov["projects"]}
        self.assertEqual(by_name[("Current Song Project", False)]["status"], "ok")
        self.assertEqual(by_name[("Old Song Project", False)]["status"], "external")
        self.assertEqual(by_name[("Song B Project", True)]["status"], "missing")
        self.assertEqual(by_name[("Song A Project", True)]["bucket"], "Finished")
        self.assertTrue(by_name[("Song A Project", False)]["possible_copies"])
        self.assertEqual(ov["totals"]["outside_library"], 3)
        self.assertEqual(len(ov["loose_sets"]), 1)
        self.assertEqual(by_name[("Current Song Project", False)]["backup_sets"], 2)


class InboxTests(FakeHome):
    def items(self):
        data = inbox.list_inboxes(self.cfg)
        inbox.mark_used_by_sets(data, self.con)
        return {i["name"]: i for ib in data["inboxes"] for i in ib["items"]}

    def test_suggestions(self):
        it = self.items()
        # Installers from plugin makers are filed, not trashed; others are trash candidates to check.
        self.assertTrue(it["Serum_x64_installer.dmg"]["suggestion"]["dest"].endswith("Music/Plugin Installers"))
        self.assertTrue(it["Ozone 11.pkg"]["suggestion"]["dest"].endswith("Music/Plugin Installers"))
        self.assertEqual((it["SomeApp-2.1.dmg"]["suggestion"]["action"], it["SomeApp-2.1.dmg"]["suggestion"]["risk"]),
                         ("trash", "review"))
        self.assertEqual(it["Drum Pack Vol 2.zip"]["suggestion"]["rule"], "Already unzipped")
        self.assertEqual(it["Drum Pack Vol 2.zip"]["suggestion"]["risk"], "safe")
        self.assertTrue(it["Screenshot 2026-07-01 at 10.00.00.png"]["suggestion"]["dest"].endswith("Pictures/Screenshots/2026"))
        self.assertEqual(it["Drum Pack Vol 2"]["category"], "audio")
        self.assertTrue(it["Drum Pack Vol 2"]["suggestion"]["dest"].endswith("Music/Samples"))
        self.assertEqual(it["Old Song Project"]["kind"], "ableton-project")
        self.assertTrue(it["Old Song Project"]["suggestion"]["dest"].endswith("Ableton Projects/Active"))
        self.assertEqual(it["mystery_file"]["category"], "document")  # sniffed from %PDF

    def test_desktop_is_left_alone_while_active(self):
        it = self.items()
        self.assertEqual(it["notes.txt"]["suggestion"]["action"], "keep")
        self.assertEqual(it["Current Song Project"]["suggestion"]["action"], "keep")

    def test_files_used_by_sets_are_kept(self):
        item = self.items()["vocal chop.wav"]
        self.assertIn("used_by", item)
        self.assertEqual(item["suggestion"]["action"], "keep")

    def test_trash_rules_never_match_folders(self):
        bundle = self.items()["Installer Bundle"]
        self.assertEqual(bundle["category"], "installer")  # mostly a .pkg by size...
        self.assertNotEqual((bundle.get("suggestion") or {}).get("action"), "trash")  # ...but it has a license key

    def test_disabled_rules_are_skipped(self):
        cfg = json.loads(json.dumps(self.cfg))
        for r in cfg["rules"]:
            if r["name"] == "Installers already used":
                r["enabled"] = False
        data = inbox.list_inboxes(cfg)
        item = next(i for ib in data["inboxes"] for i in ib["items"] if i["name"] == "SomeApp-2.1.dmg")
        self.assertIsNone(item["suggestion"])

    def test_autosort_only_runs_auto_rules(self):
        self.assertEqual(inbox.autosort(self.cfg, dry_run=True), [])
        cfg = json.loads(json.dumps(self.cfg))
        cfg["rules"][0]["auto"] = True  # unfinished downloads
        res = inbox.autosort(cfg, dry_run=True)
        self.assertEqual([os.path.basename(r["src"]) for r in res], ["big-video.crdownload"])
        self.assertTrue(res[0]["dry_run"])


class PurgeTests(FakeHome):
    def findings(self):
        return {(x["kind"], os.path.basename(x["path"])): x for x in purge.findings(self.con, self.cfg)}

    def test_findings(self):
        f = self.findings()
        self.assertEqual(f[("cache", "com.google.Chrome")]["risk"], "safe")
        self.assertNotIn(("cache", "com.spotify.client"), f)  # may hold offline music
        self.assertEqual(f[("installer", "SomeApp-2.1.dmg")]["risk"], "review")
        self.assertEqual(f[("installer", "big-video.crdownload")]["risk"], "safe")
        self.assertEqual(f[("archive", "Drum Pack Vol 2.zip")]["risk"], "safe")  # contents verified
        self.assertIn(("ableton", "Backup"), f)
        self.assertNotIn(("cache", "tiny"), f)
        self.assertNotIn(("installer", "Serum_x64_installer.dmg"), f)  # filed by Catch-alls instead

    def test_safe_means_rebuildable_or_redundant_only(self):
        safe = {k for k, v in self.findings().items() if v["risk"] == "safe" and v["action"]}
        self.assertEqual(safe, {("cache", "com.google.Chrome"), ("installer", "big-video.crdownload"),
                                ("archive", "Drum Pack Vol 2.zip")})

    def test_duplicate_keeps_the_organised_icloud_copy(self):
        f = self.findings()
        self.assertIn(("dupe", "report copy.pdf"), f)
        self.assertTrue(f[("dupe", "report copy.pdf")]["keep"].endswith("Documents/report.pdf"))

    def test_sound_library_copies_are_not_duplicates(self):
        self.assertFalse(any("User Library" in x["path"] or "User Library" in x.get("keep", "")
                             for x in purge.findings(self.con, self.cfg)))

    def test_duplicate_used_from_downloads_keeps_both(self):
        f = self.findings()
        d = f[("dupe", "song a master.wav")]
        self.assertIsNone(d["action"])  # nothing to trash until Collect All
        self.assertIn("Keep both", d["why"])

    def test_catchalls_and_cleanup_agree_on_duplicates(self):
        data = inbox.list_inboxes(self.cfg)
        inbox.mark_used_by_sets(data, self.con, self.cfg)
        item = next(i for ib in data["inboxes"] for i in ib["items"] if i["name"] == "report copy.pdf")
        self.assertEqual(item["suggestion"]["action"], "trash")
        self.assertIn("Documents/report.pdf", item["suggestion"]["reason"])

    def test_edited_sample_makes_archive_check_first(self):
        wav = self.home / "Downloads" / "Drum Pack Vol 2" / "kick_0.wav"
        data = bytearray(wav.read_bytes())
        data[100] ^= 0xFF  # same size, different audio
        wav.write_bytes(bytes(data))
        os.utime(wav, (wav.stat().st_atime, wav.stat().st_mtime + 5))  # as any edit would
        try:
            self.assertEqual(self.findings()[("archive", "Drum Pack Vol 2.zip")]["risk"], "review")
        finally:
            data[100] ^= 0xFF
            wav.write_bytes(bytes(data))

    def test_folder_with_used_samples_is_blocked_at_click_time(self):
        from macclean import safety
        idx = safety.UsedIndex(self.con)
        old_song = self.home / "Downloads" / "Old Song Project"
        vocal = self.home / "Downloads" / "vocal chop.wav"
        self.assertIn("Old Song", safety.preflight(idx, str(vocal), "move"))
        self.assertIn("Old Song", safety.preflight(idx, str(vocal), "trash"))
        self.assertIsNone(safety.preflight(idx, str(old_song), "move"))  # its own set moves with it

    def test_unreadable_sets_suppress_audio_duplicates(self):
        self.con.execute("INSERT INTO ableton_sets (path, error) VALUES ('/x/y.als', 'Only in iCloud')")
        try:
            kinds = [(x["kind"], x["title"]) for x in purge.findings(self.con, self.cfg)]
            self.assertNotIn(("dupe", "song a master.wav"), kinds)
            self.assertIn(("dupe", "report copy.pdf"), kinds)  # not audio, still listed
            self.assertEqual(purge.summary(self.con, self.cfg, [])["unchecked_sets"], 1)
        finally:
            self.con.execute("DELETE FROM ableton_sets WHERE path='/x/y.als'")

    def test_never_suggests_trashing_a_sample_a_set_uses(self):
        paths = [x["path"] for x in purge.findings(self.con, self.cfg) if x["action"]]
        self.assertFalse(any(p.endswith("vocal chop.wav") for p in paths))
        dupe = [x for x in purge.findings(self.con, self.cfg) if x["kind"] == "dupe"]
        self.assertTrue(dupe and dupe[0]["keep"].endswith("vocal chop.wav"))

    def test_survey_mentions_the_essentials(self):
        text = survey.build(self.con, self.cfg)
        for needle in ("## Ableton", "Old Song Project", "## Catch-all folders", "iCloud Drive structure"):
            self.assertIn(needle, text)


class PackAndPresetTests(FakeHome):
    """Lesson from a real cleanup: racks in the User Library load Pack samples and
    Max devices, so a Pack is only unused if no set AND no preset uses it."""

    def packs(self):
        return {p["name"]: p for p in ableton.packs_overview(self.con, self.cfg)["packs"]}

    def test_pack_used_only_by_a_rack_is_in_use(self):
        p = self.packs()
        self.assertEqual(p["Drive and Glow"]["status"], "used")
        self.assertEqual(p["Drive and Glow"]["sets"], [])
        self.assertTrue(p["Drive and Glow"]["presets"][0].endswith("[dnksaus] Stock Drum Selecta (Suite).adg"))
        self.assertEqual(p["Max for Live Essentials"]["status"], "used")  # via the rack's .amxd
        self.assertEqual(p["Synth Essentials"]["status"], "used")

    def test_pack_used_by_a_set(self):
        self.assertEqual(self.packs()["Drum Booth"]["status"], "used")

    def test_presets_inside_a_pack_dont_count_as_use(self):
        self.assertEqual(self.packs()["Grand Piano"]["status"], "unused")

    def test_missing_pack_that_is_still_used(self):
        self.assertEqual(self.packs()["Lost Pack"]["status"], "missing-used")

    def test_unreadable_preset_means_nothing_is_called_unused(self):
        self.con.execute("INSERT INTO ableton_presets (path, error) VALUES ('/x/y.adg', 'Only in iCloud')")
        try:
            self.assertEqual(self.packs()["Grand Piano"]["status"], "unknown")
        finally:
            self.con.execute("DELETE FROM ableton_presets WHERE path='/x/y.adg'")

    def test_presets_are_not_loose_sets(self):
        self.assertEqual(len(ableton.overview(self.con, self.cfg)["loose_sets"]), 1)

    def test_rack_parse_ignores_where_samples_came_from(self):
        rack = next(self.home.rglob("[[]dnksaus[]] Stock Drum Selecta (Suite).adg"))
        refs = ableton.parse_set(str(rack))["refs"]
        self.assertEqual(len(refs), 2)
        self.assertFalse(any("where-it-came-from" in r["path"] for r in refs))

    def test_file_a_preset_uses_is_kept_and_blocked(self):
        from macclean import safety
        oneshot = self.home / "Downloads" / "bass one-shot.wav"
        msg = safety.preflight(safety.UsedIndex(self.con), str(oneshot), "trash")
        self.assertIn("Bass Preset Selecta", msg)
        data = inbox.list_inboxes(self.cfg)
        inbox.mark_used_by_sets(data, self.con, self.cfg)
        item = next(i for ib in data["inboxes"] for i in ib["items"] if i["name"] == "bass one-shot.wav")
        self.assertEqual(item["suggestion"]["action"], "keep")
        self.assertIn("preset", item["suggestion"]["reason"])

    def test_live_folders_and_rekordbox_are_protected(self):
        from macclean import safety
        cloud = self.home / config.ICLOUD_REL
        ul = cloud / "Active Storage" / "User Library"
        packs = self.home / "Music" / "Ableton" / "Factory Packs"
        for path in (ul, ul / "Presets", packs / "Grand Piano", cloud / "Active Storage" / "rekordbox",
                     cloud / "Active Storage" / "rekordbox" / "master.db"):
            self.assertIsNotNone(safety.protected_reason(str(path), self.cfg), path)
        # deeper inside the User Library is fine (the used-by check still guards each file)
        self.assertIsNone(safety.protected_reason(str(ul / "Presets" / "Instruments"), self.cfg))

    def test_library_cfg(self):
        from macclean import live_prefs
        info = live_prefs.read_library()
        self.assertTrue(info["cfg_path"].endswith("Live 12.4.6/Library.cfg"))  # newest Live wins
        self.assertTrue(info["user_library"].endswith("Active Storage/User Library"))
        self.assertIn("Drive and Glow", [p["name"] for p in info["packs"]])
        self.assertEqual(info["packs"][0]["id"], "www.ableton.com/0")  # pasted-link junk cleaned
        self.assertEqual([os.path.basename(p["path"]) for p in info["places"]], ["Active Storage", "ASYM Music"])
        self.assertTrue(info["default_template"].endswith("Templates/Default.als"))


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = Path(self.tmp)
        self._old = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        (self.home / "Downloads").mkdir()
        self.f = self.home / "Downloads" / "a.pdf"
        self.f.write_text("x")
        self.cfg = config.load_config()

    def tearDown(self):
        os.environ["HOME"] = self._old
        shutil.rmtree(self.tmp)

    def test_move_never_overwrites_and_undo_restores(self):
        dest = self.home / "Docs"
        dest.mkdir()
        (dest / "a.pdf").write_text("existing")
        r = actions.move(self.f, dest, self.cfg)
        self.assertEqual(Path(r["dst"]).name, "a 2.pdf")
        self.assertEqual((dest / "a.pdf").read_text(), "existing")
        actions.undo(r["id"])
        self.assertTrue(self.f.exists())
        self.assertTrue(actions.history()[0]["undone"])
        with self.assertRaises(actions.ActionError):
            actions.undo(r["id"])

    def test_trash_goes_to_user_trash(self):
        r = actions.trash(self.f, self.cfg)
        self.assertTrue((self.home / ".Trash" / "a.pdf").exists())
        actions.undo(r["id"])
        self.assertTrue(self.f.exists())

    def test_refuses_protected_and_outside_paths(self):
        res = actions.apply([
            {"path": str(self.home / "Downloads"), "action": "trash"},
            {"path": "/etc/hosts", "action": "trash"},
            {"path": str(self.f), "action": "move", "dest": "/tmp/elsewhere"},
            {"path": str(self.f), "action": "move"},
        ], self.cfg)
        self.assertEqual([r["ok"] for r in res], [False] * 4)
        self.assertTrue(self.f.exists())

    def test_refuses_app_data_and_libraries(self):
        h = self.home
        for rel in ("Library/Keychains", "Library/Caches", "Library/Mobile Documents",
                    "Library/Application Support/Ableton", "Library/Containers/com.spotify.client",
                    "Music/Ableton/User Library", "Pictures/Photos Library.photoslibrary"):
            (h / rel).mkdir(parents=True, exist_ok=True)
            res = actions.apply([{"path": str(h / rel), "action": "trash"}], self.cfg)
            self.assertFalse(res[0]["ok"], rel)
            self.assertTrue((h / rel).exists(), rel)
        # ...but a cache inside ~/Library/Caches, or a project inside ~/Music/Ableton/Projects, is fine.
        (h / "Library/Caches/com.google.Chrome").mkdir(parents=True)
        (h / "Music/Ableton/Projects/Song Project").mkdir(parents=True)
        res = actions.apply([{"path": str(h / "Library/Caches/com.google.Chrome"), "action": "trash"},
                             {"path": str(h / "Music/Ableton/Projects/Song Project"), "action": "trash"}], self.cfg)
        self.assertEqual([r["ok"] for r in res], [True, True])

    def test_grouped_trash_undoes_in_one_go(self):
        folder = self.home / "Samples"
        for i in range(5):
            (folder / f"s{i}.wav.asd").parent.mkdir(exist_ok=True)
            (folder / f"s{i}.wav.asd").write_text("x")
        (folder / "s0.wav").write_text("audio")
        res = purge.trash_asd(str(folder), self.cfg)
        self.assertTrue(res[0]["ok"])
        self.assertFalse(Path(res[0]["dst"]).name.startswith("."))  # visible in Finder
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["s0.wav"])
        self.assertEqual(len([e for e in actions.history() if not e["undone"]]), 1)
        actions.undo(res[0]["id"])
        self.assertEqual(len(list(folder.glob("*.asd"))), 5)

    def test_preflight_rechecks_at_click_time(self):
        from macclean import safety
        idx = safety.UsedIndex(None)
        self.assertIsNone(safety.preflight(idx, str(self.f), "trash", {"mtime": self.f.stat().st_mtime, "size": 1}))
        self.assertIn("changed", safety.preflight(idx, str(self.f), "trash", {"mtime": 0, "size": 1}))
        self.assertIsNone(safety.preflight(idx, str(self.f), "move", {"mtime": 0, "size": 1}))

    def test_icloud_main_folders_and_symlinks(self):
        cloud = self.home / config.ICLOUD_REL
        (cloud / "Documents").mkdir(parents=True)
        (cloud / "loose.pdf").write_text("x")
        res = actions.apply([{"path": str(cloud / "Documents"), "action": "trash"},
                             {"path": str(cloud / "loose.pdf"), "action": "trash"}], self.cfg)
        self.assertEqual([r["ok"] for r in res], [False, True])
        (self.home / "Documents").mkdir()
        link = self.home / "Downloads" / "docs link"
        os.symlink(self.home / "Documents", link)
        self.assertTrue(actions.apply([{"path": str(link), "action": "trash"}], self.cfg)[0]["ok"])
        self.assertTrue((self.home / "Documents").is_dir())

    def test_saved_settings_get_new_default_rules(self):
        old = [{"name": "Old screenshots", "when": {"older_than_days": 14}, "action": "trash"},
               {"name": "Images", "when": {"category": ["image"]}, "action": "move", "dest": "~/Pics", "enabled": False},
               {"name": "My own rule", "when": {"ext": [".mid"]}, "action": "move", "dest": "~/MIDI"}]
        config.config_path().write_text(json.dumps({"inboxes": ["~/Downloads"], "rules": old}))
        rules = {r["name"]: r for r in config.load_config()["rules"]}
        self.assertEqual(rules["Old screenshots"]["action"], "move")  # the risky old default is gone
        self.assertEqual((rules["Images"]["dest"], rules["Images"]["enabled"]), ("~/Pics", False))  # kept edits
        self.assertIn("My own rule", rules)
        self.assertIn("Plugin & instrument installers", rules)

    def test_icloud_drive_shorthand_expands(self):
        p = config.expand("iCloud Drive/Documents/2026", self.cfg)
        self.assertEqual(p, self.home / config.ICLOUD_REL / "Documents" / "2026")


class ServerTests(FakeHome):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from macclean import server
        cls.server = server
        cls.httpd = server.make_server(0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        super().tearDownClass()

    def req(self, path, body=None, token=True):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Macclean-Token"] = self.server.TOKEN
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers,
                                   data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(r) as resp:
            return json.loads(resp.read())

    def test_get_endpoints(self):
        for p in ("/api/status", "/api/overview", "/api/tree", "/api/inbox", "/api/purge",
                  "/api/ableton", "/api/config", "/api/history", "/api/destinations"):
            self.assertNotIn("error", self.req(p), p)

    def test_page_has_token(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r:
            self.assertIn(self.server.TOKEN, r.read().decode())

    def test_post_requires_token(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.req("/api/apply", {"items": []}, token=False)
        self.assertEqual(cm.exception.code, 403)

    def test_bad_config_rejected(self):
        r = self.req("/api/config", {"config": {"inboxes": [], "rules": []}})
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
