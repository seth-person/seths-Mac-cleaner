import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import macclean  # noqa: E402
from macclean import updater  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "macos"))
import build_app  # noqa: E402
import build_release  # noqa: E402

NEW = "99.0.0"


def fake_runtime(root: Path) -> Path:
    """A stand-in for a python-build-standalone tree (enough for the layout tests)."""
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "python3.12").write_bytes(b"\xcf\xfa\xed\xfe fake mach-o")
    (root / "bin" / "pip3").write_text("#!/bin/sh\n")
    (root / "lib" / "python3.12" / "idlelib").mkdir(parents=True)
    (root / "lib" / "python3.12" / "os.py").write_text("")
    (root / "lib" / "python3.12" / "lib-dynload").mkdir()
    (root / "lib" / "python3.12" / "lib-dynload" / "_tkinter.so").write_bytes(b"x")
    (root / "lib" / "libtcl9.0.dylib").write_bytes(b"x")
    (root / "include").mkdir()
    return root


def zip_app(app: Path, dest: Path) -> None:
    """Zip a bundle the way `ditto -c -k --keepParent` does (symlinks kept)."""
    with zipfile.ZipFile(dest, "w") as zf:
        for p in sorted(app.parent.rglob("*")):
            if not str(p).startswith(str(app)):
                continue
            arc = str(p.relative_to(app.parent))
            if p.is_symlink():
                info = zipfile.ZipInfo(arc)
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                zf.writestr(info, os.readlink(p))
            elif p.is_file():
                info = zipfile.ZipInfo(arc)
                info.external_attr = (stat.S_IFREG | (p.stat().st_mode & 0o777)) << 16
                zf.writestr(info, p.read_bytes())


class Sandbox(unittest.TestCase):
    """A fake home folder plus a fake GitHub release of version NEW."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        (self.home / "Library" / "Logs").mkdir(parents=True)
        self.root = self.home / "Library" / "Application Support" / "Mac Cleaner"
        self.apps = self.home / "Applications"
        self.env_backup = dict(os.environ)
        os.environ.update(HOME=str(self.home), MACCLEAN_INSTALL_ROOT=str(self.root),
                          MACCLEAN_APPS_DIR=str(self.apps))
        os.environ.pop("MACCLEAN_APP_BUNDLE", None)

        # Source tree of the "new" release.
        src = self.tmp / "src"
        shutil.copytree(REPO_ROOT, src, ignore=shutil.ignore_patterns(".git", "__pycache__", "dist", "build"))
        init = src / "macclean" / "__init__.py"
        init.write_text(init.read_text().replace(macclean.__version__, NEW))
        cl = src / "CHANGELOG.md"
        cl.write_text(cl.read_text().replace("\n## ", f"\n## {NEW}\n\n- test\n\n## ", 1))
        out = self.tmp / "dist"
        subprocess.run([sys.executable, str(src / "scripts" / "build_release.py"), str(out)], check=True,
                       capture_output=True)
        subprocess.run([sys.executable, str(src / "macos" / "build_app.py"), "--arm",
                        str(fake_runtime(self.tmp / "rt")), "--out", str(self.tmp / "appbuild"),
                        "--assemble-only"], check=True, capture_output=True)
        zip_app(self.tmp / "appbuild" / "Mac Cleaner.app", out / f"Mac-Cleaner-{NEW}.zip")
        self.files = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}
        self.files["SHA256SUMS"] = "".join(
            f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in self.files.items()
            if n.endswith((".tar.gz", ".zip"))).encode()
        self.release = {"tag_name": "v" + NEW, "body": "notes", "html_url": "x", "published_at": "",
                        "assets": [{"name": n, "url": "fake://" + n} for n in self.files]}

        self._saved = {k: getattr(updater, k) for k in
                       ("_request", "running_from_install", "_check_staged_engine", "_app_pid")}
        updater._request = self.fake_request
        updater._check_staged_engine = lambda app, version: None  # can't run a macOS binary here
        updater._app_pid = lambda: 2 ** 22 + 12345  # a process that doesn't exist: swap right away

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(updater, k, v)
        os.environ.clear()
        os.environ.update(self.env_backup)
        shutil.rmtree(self.tmp)

    def fake_request(self, url, accept=None):
        if url.endswith("/releases/latest"):
            return json.dumps(self.release).encode()
        return self.files[url[len("fake://"):]]

    def make_installed_app(self, version):
        """Pretend an older Mac Cleaner.app is installed and running."""
        app = self.apps / "Mac Cleaner.app"
        (app / "Contents" / "MacOS").mkdir(parents=True)
        import plistlib
        with open(app / "Contents" / "Info.plist", "wb") as f:
            plistlib.dump({"CFBundleShortVersionString": version}, f)
        os.environ["MACCLEAN_APP_BUNDLE"] = str(app)
        return app


class VersionTests(unittest.TestCase):
    def test_parse_and_compare(self):
        self.assertEqual(updater.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updater.parse_version("0.10"), (0, 10, 0))
        self.assertGreater(updater.parse_version("0.10.0"), updater.parse_version("0.9.9"))


class AppModeTests(Sandbox):
    def test_update_swaps_bundle_and_keeps_previous(self):
        app = self.make_installed_app("0.0.1")
        info = updater.check(force=True)
        self.assertEqual((info["mode"], info["available"], info["blocked"]), ("app", True, None))
        rel = updater.latest_release()
        staged = updater._stage_app(rel)
        self.assertEqual(updater._bundle_version(staged), NEW)
        self.assertTrue(os.path.islink(staged / "Contents/Resources/python/bin/python3"))
        proc = updater._swap_to(staged)
        proc.wait(timeout=30)
        self.assertEqual(updater._bundle_version(app), NEW)
        self.assertEqual(updater._app_previous_version(), "0.0.1")

        # Roll back: the previous bundle comes back, the new one becomes "previous".
        updater._swap_to(updater._previous_app()).wait(timeout=30)
        self.assertEqual(updater._bundle_version(app), "0.0.1")
        self.assertEqual(updater._app_previous_version(), NEW)

    def test_install_latest_hands_over_to_relaunch(self):
        app = self.make_installed_app("0.0.1")
        real_swap = updater._swap_to
        updater._swap_to = lambda new: real_swap(new).wait(timeout=30)
        try:
            res = updater.install_latest()
        finally:
            updater._swap_to = real_swap
        self.assertTrue(res["relaunch"])
        self.assertEqual(updater._bundle_version(app), NEW)
        self.assertEqual(res["to"], NEW)

    def test_checksum_mismatch_changes_nothing(self):
        app = self.make_installed_app("0.0.1")
        name = f"Mac-Cleaner-{NEW}.zip"
        self.files[name] = self.files[name][:-10] + b"0" * 10
        with self.assertRaises(updater.UpdateError):
            updater.install_latest()
        self.assertEqual(updater._bundle_version(app), "0.0.1")

    def test_running_from_disk_image_is_blocked(self):
        self.make_installed_app("0.0.1")
        os.environ["MACCLEAN_APP_BUNDLE"] = "/private/var/folders/x/AppTranslocation/ABC/d/Mac Cleaner.app"
        self.assertIn("Applications", updater.check(force=True)["blocked"])
        with self.assertRaises(updater.UpdateError):
            updater.install_latest()

    def test_app_cleans_up_old_browser_install(self):
        (self.root / "versions" / "0.2.0").mkdir(parents=True)
        os.symlink("versions/0.2.0", self.root / "current")
        self.make_installed_app("0.0.1")
        updater.check(force=True)
        self.assertFalse((self.root / "versions").exists())
        self.assertFalse((self.root / "current").is_symlink())


class LegacyModeTests(Sandbox):
    """The 0.2.0 browser-based install: code tarball updates, then the switch to the app."""

    def setUp(self):
        super().setUp()
        v = macclean.__version__
        shutil.copytree(REPO_ROOT / "macclean", self.root / "versions" / v / "macclean",
                        ignore=shutil.ignore_patterns("__pycache__"))
        os.symlink(f"versions/{v}", self.root / "current")
        launcher = self.apps / "Mac Cleaner.app" / "Contents" / "MacOS" / "Mac Cleaner"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("#!/bin/bash\nnohup python3 -m macclean serve &\n")
        updater.running_from_install = lambda: True

    def test_tarball_update_then_rollback(self):
        info = updater.check(force=True)
        self.assertEqual(info["mode"], "legacy")
        self.assertTrue(info["app_available"])
        res = updater.install_latest()
        self.assertEqual(res["to"], NEW)
        self.assertEqual(updater.current_target(), NEW)
        back = updater.rollback()
        self.assertEqual(back["to"], macclean.__version__)

    def test_switch_to_app_replaces_old_launcher(self):
        res = updater.migrate_to_app()
        app = Path(res["path"])
        self.assertEqual(app, self.apps / "Mac Cleaner.app")
        self.assertEqual(updater._bundle_version(app), NEW)
        self.assertFalse(updater._is_legacy_launcher(app))

    def test_broken_tarball_release_is_rejected(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            data = b"raise SystemExit('boom')\n"
            ti = tarfile.TarInfo("macclean/__init__.py")
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        name = f"mac-cleaner-{NEW}.tar.gz"
        self.files[name] = buf.getvalue()
        self.files["SHA256SUMS"] = f"{hashlib.sha256(buf.getvalue()).hexdigest()}  {name}\n".encode()
        with self.assertRaises(updater.UpdateError):
            updater.install_latest()
        self.assertEqual(updater.current_target(), macclean.__version__)


class SourceModeTests(Sandbox):
    def test_source_checkout_does_not_self_update(self):
        self.assertEqual(updater.mode(), "source")
        with self.assertRaises(updater.UpdateError):
            updater.install_latest()


class SafetyTests(unittest.TestCase):
    def test_refuses_path_traversal(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tf:
                ti = tarfile.TarInfo("../evil.txt")
                ti.size = 1
                tf.addfile(ti, io.BytesIO(b"x"))
            with self.assertRaises(updater.UpdateError):
                updater._safe_extract(buf.getvalue(), tmp / "x")
            self.assertFalse((tmp / "evil.txt").exists())

            zbuf = io.BytesIO()
            with zipfile.ZipFile(zbuf, "w") as zf:
                zf.writestr("../evil.txt", "x")
            with self.assertRaises(updater.UpdateError):
                updater._unzip(zbuf.getvalue(), tmp / "z" / "out")
            self.assertFalse((tmp / "z" / "evil.txt").exists())
        finally:
            shutil.rmtree(tmp)


class BuildTests(unittest.TestCase):
    def test_bundle_layout(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            app = build_app.build(fake_runtime(tmp / "rt"), None, tmp / "out", native=False)
            res = app / "Contents" / "Resources"
            self.assertEqual(updater._bundle_version(app), macclean.__version__)
            self.assertTrue((res / "app" / "macclean" / "server.py").is_file())
            self.assertEqual(sorted(p.name for p in (res / "python" / "bin").iterdir()), ["python3", "python3.12"])
            for gone in ("include", "lib/libtcl9.0.dylib", "lib/python3.12/idlelib",
                         "lib/python3.12/lib-dynload/_tkinter.so"):
                self.assertFalse((res / "python" / gone).exists(), gone)
            self.assertTrue((res / "python" / "lib" / "python3.12" / "os.py").exists())
        finally:
            shutil.rmtree(tmp)

    def test_current_version_has_changelog_entry(self):
        self.assertTrue(build_release.notes(macclean.__version__).strip())


class InstallScriptTests(Sandbox):
    def test_installs_app_and_removes_old_launcher(self):
        old = self.apps / "Mac Cleaner.app" / "Contents" / "MacOS" / "Mac Cleaner"
        old.parent.mkdir(parents=True)
        old.write_text("#!/bin/bash\n")
        env = {**os.environ, "MACCLEAN_APP_ZIP": str(self.tmp / "dist" / f"Mac-Cleaner-{NEW}.zip"),
               "MACCLEAN_NO_LAUNCH": "1"}
        r = subprocess.run(["bash", str(REPO_ROOT / "install.sh")], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        app = self.apps / "Mac Cleaner.app"
        self.assertEqual(updater._bundle_version(app), NEW)
        self.assertFalse(updater._is_legacy_launcher(app))
        r = subprocess.run(["bash", str(REPO_ROOT / "install.sh"), "--uninstall"], env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(app.exists())


if __name__ == "__main__":
    unittest.main()
