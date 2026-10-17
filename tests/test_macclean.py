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
        self.assertEqual(it["Serum_x64_installer.dmg"]["suggestion"]["action"], "trash")
        self.assertIsNone(it["Ozone 11.pkg"]["suggestion"])  # too fresh
        self.assertEqual(it["Drum Pack Vol 2.zip"]["suggestion"]["rule"], "Already unzipped")
        self.assertEqual(it["Drum Pack Vol 2"]["category"], "audio")
        self.assertTrue(it["Drum Pack Vol 2"]["suggestion"]["dest"].endswith("Music/Samples"))
        self.assertEqual(it["Old Song Project"]["kind"], "ableton-project")
        self.assertTrue(it["Old Song Project"]["suggestion"]["dest"].endswith("Ableton Projects/Active"))
        self.assertEqual(it["mystery_file"]["category"], "document")  # sniffed from %PDF

    def test_desktop_is_left_alone_while_active(self):
        it = self.items()
        self.assertEqual(it["notes.txt"]["suggestion"]["action"], "keep")
        self.assertEqual(it["Current Song Project"]["suggestion"]["action"], "keep")

    def test_files_used_by_sets_are_flagged(self):
        self.assertIn("used_by", self.items()["vocal chop.wav"])

    def test_autosort_only_runs_auto_rules(self):
        self.assertEqual(inbox.autosort(self.cfg, dry_run=True), [])
        cfg = json.loads(json.dumps(self.cfg))
        cfg["rules"][0]["auto"] = True  # unfinished downloads
        res = inbox.autosort(cfg, dry_run=True)
        self.assertEqual([os.path.basename(r["src"]) for r in res], ["big-video.crdownload"])
        self.assertTrue(res[0]["dry_run"])


class PurgeTests(FakeHome):
    def test_findings(self):
        f = {(x["kind"], os.path.basename(x["path"])): x for x in purge.findings(self.con, self.cfg)}
        self.assertIn(("cache", "com.spotify.client"), f)
        self.assertIn(("installer", "Serum_x64_installer.dmg"), f)
        self.assertIn(("installer", "big-video.crdownload"), f)
        self.assertIn(("archive", "Drum Pack Vol 2.zip"), f)
        self.assertIn(("ableton", "Backup"), f)
        self.assertNotIn(("cache", "tiny"), f)

    def test_never_suggests_trashing_a_sample_a_set_uses(self):
        paths = [x["path"] for x in purge.findings(self.con, self.cfg) if x["action"]]
        self.assertFalse(any(p.endswith("vocal chop.wav") for p in paths))
        dupe = [x for x in purge.findings(self.con, self.cfg) if x["kind"] == "dupe"]
        self.assertTrue(dupe and dupe[0]["keep"].endswith("vocal chop.wav"))

    def test_survey_mentions_the_essentials(self):
        text = survey.build(self.con, self.cfg)
        for needle in ("## Ableton", "Old Song Project", "## Catch-all folders", "iCloud Drive structure"):
            self.assertIn(needle, text)


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
