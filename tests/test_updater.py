import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from macclean import updater  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import build_release  # noqa: E402


class VersionTests(unittest.TestCase):
    def test_parse_and_compare(self):
        self.assertEqual(updater.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updater.parse_version("0.10"), (0, 10, 0))
        self.assertGreater(updater.parse_version("0.10.0"), updater.parse_version("0.9.9"))


class InstallTests(unittest.TestCase):
    """install.sh, then updater.install_latest against a fake release."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.root = self.home / "Library" / "Application Support" / "Mac Cleaner"
        self.env_backup = dict(os.environ)
        os.environ.update(HOME=str(self.home), MACCLEAN_INSTALL_ROOT=str(self.root))
        env = {**os.environ, "MACCLEAN_PYTHON": sys.executable, "MACCLEAN_SKIP_TOKEN": "1",
               "MACCLEAN_NO_LAUNCH": "1"}
        r = subprocess.run(["bash", str(REPO_ROOT / "install.sh")], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        import macclean
        self.version = macclean.__version__

        # A fake newer release, built the same way CI builds real ones.
        self.newver = "99.0.0"
        src = self.tmp / "src"
        shutil.copytree(REPO_ROOT, src, ignore=shutil.ignore_patterns(".git", "__pycache__", "dist"))
        init = src / "macclean" / "__init__.py"
        init.write_text(init.read_text().replace(self.version, self.newver))
        cl = src / "CHANGELOG.md"
        cl.write_text(cl.read_text().replace("\n## ", f"\n## {self.newver}\n\n- test\n\n## ", 1))
        out = self.tmp / "dist"
        subprocess.run([sys.executable, str(src / "scripts" / "build_release.py"), str(out)], check=True,
                       capture_output=True)
        self.files = {p.name: p.read_bytes() for p in out.iterdir()}
        self.release = {"tag_name": "v" + self.newver, "body": "notes", "html_url": "x", "published_at": "",
                        "assets": [{"name": n, "url": "fake://" + n} for n in self.files]}
        self._orig_request = updater._request
        updater._request = self.fake_request
        # Pretend this code runs from the installed copy.
        self._orig_running = updater.running_from_install
        updater.running_from_install = lambda: True

    def tearDown(self):
        updater._request = self._orig_request
        updater.running_from_install = self._orig_running
        os.environ.clear()
        os.environ.update(self.env_backup)
        shutil.rmtree(self.tmp)

    def fake_request(self, url, accept=None):
        if url.endswith("/releases/latest"):
            return json.dumps(self.release).encode()
        return self.files[url[len("fake://"):]]

    def test_installer_layout(self):
        self.assertEqual(os.readlink(self.root / "current"), f"versions/{self.version}")
        self.assertTrue((self.root / "versions" / self.version / "macclean" / "updater.py").is_file())
        launcher = self.home / "Applications" / "Mac Cleaner.app" / "Contents" / "MacOS" / "Mac Cleaner"
        self.assertTrue(os.access(launcher, os.X_OK))
        self.assertIn("current", launcher.read_text())

    def test_update_then_rollback(self):
        info = updater.check(force=True)
        self.assertTrue(info["available"])
        self.assertEqual(info["latest"], self.newver)
        res = updater.install_latest()
        self.assertEqual(res["to"], self.newver)
        self.assertEqual(updater.current_target(), self.newver)
        self.assertIn(self.version, updater.installed_versions())
        back = updater.rollback()
        self.assertEqual((back["from"], back["to"]), (self.newver, self.version))
        self.assertEqual(updater.current_target(), self.version)

    def test_checksum_mismatch_changes_nothing(self):
        name = f"mac-cleaner-{self.newver}.tar.gz"
        self.files[name] = self.files[name][:-10] + b"0" * 10
        with self.assertRaises(updater.UpdateError):
            updater.install_latest()
        self.assertEqual(updater.current_target(), self.version)
        self.assertEqual(updater.installed_versions(), [self.version])

    def test_broken_release_is_rejected(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            data = b"raise SystemExit('boom')\n"
            ti = tarfile.TarInfo("macclean/__init__.py")
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        name = f"mac-cleaner-{self.newver}.tar.gz"
        self.files[name] = buf.getvalue()
        import hashlib
        self.files["SHA256SUMS"] = f"{hashlib.sha256(buf.getvalue()).hexdigest()}  {name}\n".encode()
        with self.assertRaises(updater.UpdateError):
            updater.install_latest()
        self.assertEqual(updater.current_target(), self.version)

    def test_refuses_path_traversal(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            ti = tarfile.TarInfo("../evil.txt")
            ti.size = 1
            tf.addfile(ti, io.BytesIO(b"x"))
        with self.assertRaises(updater.UpdateError):
            updater._safe_extract(buf.getvalue(), self.tmp / "x")
        self.assertFalse((self.tmp / "evil.txt").exists())

    def test_source_checkout_does_not_self_update(self):
        updater.running_from_install = self._orig_running
        with self.assertRaises(updater.UpdateError):
            updater.install_latest()


class ReleaseNotesTests(unittest.TestCase):
    def test_current_version_has_changelog_entry(self):
        import macclean
        self.assertTrue(build_release.notes(macclean.__version__).strip())


if __name__ == "__main__":
    unittest.main()
