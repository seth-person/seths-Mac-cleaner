"""Build Mac Cleaner.app (plus .zip for updates and .dmg for first install).

Runs on macOS (the Release workflow uses a GitHub macOS runner):

  python3 macos/build_app.py --arm <python-arm64> --x86 <python-x86_64> --out build

<python-*> are python-build-standalone installs (e.g. from `uv python install
cpython-3.12-macos-aarch64-none --install-dir ...`). The two are merged into
one universal runtime so the app runs on Apple Silicon and Intel Macs.

--assemble-only skips everything that needs macOS tools (Swift, lipo,
codesign, packaging); the tests use it to check the bundle layout on Linux.
"""
from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import macclean  # noqa: E402

APP_NAME = "Mac Cleaner"
BUNDLE_ID = "com.seth-person.mac-cleaner"
EXECUTABLE = "MacCleaner"
MIN_MACOS = "12.0"
# The signing key comes from the MACOS_SIGNING_P12_BASE64 Actions secret (see
# macos/signing/README.md). Its certificate is pinned in macclean/updater.py.
IDENTITY_ENV = "MACOS_SIGNING_P12_BASE64"
IDENTITY_PASSWORD = os.environ.get("MACOS_SIGNING_P12_PASSWORD", "mac-cleaner")

# Parts of the Python runtime the app never uses.
PRUNE = [
    "include", "share", "lib/pkgconfig", "lib/libpython3.12.dylib",
    "lib/tcl9", "lib/tcl9.0", "lib/tk9.0", "lib/itcl4.3.5", "lib/thread3.0.4",
    "lib/libtcl9.0.dylib", "lib/libtcl9tk9.0.dylib",
    "lib/python3.12/idlelib", "lib/python3.12/tkinter", "lib/python3.12/turtledemo",
    "lib/python3.12/turtle.py", "lib/python3.12/ensurepip", "lib/python3.12/lib2to3",
    "lib/python3.12/pydoc_data", "lib/python3.12/test", "lib/python3.12/site-packages",
    "lib/python3.12/config-3.12-darwin",
]
PRUNE_GLOBS = ["lib/python3.12/lib-dynload/_tkinter*", "lib/tcl*", "lib/tk*", "lib/itcl*", "lib/thread*",
               "lib/libtcl*", "lib/libtk*"]
KEEP_BIN = {"python3.12"}


def run(*cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def is_macho(p: Path) -> bool:
    if p.is_symlink() or not p.is_file():
        return False
    with open(p, "rb") as f:
        return f.read(4) in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca")


def copy_runtime(arm: Path, x86: Path | None, dest: Path, native: bool) -> None:
    shutil.copytree(arm, dest, symlinks=True)
    for rel in PRUNE:
        p = dest / rel
        if p.is_symlink() or p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p)
    for pattern in PRUNE_GLOBS:
        for p in dest.glob(pattern):
            shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
    for p in (dest / "bin").iterdir():
        if p.name not in KEEP_BIN:
            p.unlink()
    os.symlink("python3.12", dest / "bin" / "python3")
    for p in list(dest.rglob("__pycache__")):
        shutil.rmtree(p)
    if x86 is None:
        return
    for p in sorted(dest.rglob("*")):
        if is_macho(p):
            other = x86 / p.relative_to(dest)
            if not other.exists():
                raise SystemExit(f"{other} is missing from the x86_64 runtime")
            if native:
                run("lipo", "-create", p, other, "-output", str(p) + ".universal")
                os.replace(str(p) + ".universal", p)


def write_info_plist(app: Path, version: str) -> None:
    info = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": EXECUTABLE,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "CFBundleIconFile": "AppIcon",
        "LSMinimumSystemVersion": MIN_MACOS,
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSHighResolutionCapable": True,
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        "NSHumanReadableCopyright": "Made for Seth.",
    }
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(info, f)


def build_icon(resources: Path, native: bool) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "icon.png"
        run(sys.executable, ROOT / "macos" / "make_icon.py", png)
        if not native:
            shutil.copy(png, resources / "AppIcon.png")
            return
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                run("sips", "-z", px, px, png, "--out", iconset / name, stdout=subprocess.DEVNULL)
        run("iconutil", "-c", "icns", iconset, "-o", resources / "AppIcon.icns")


def build_shell(macos_dir: Path) -> None:
    src = ROOT / "macos" / "MacCleaner.swift"
    with tempfile.TemporaryDirectory() as tmp:
        outs = []
        for arch in ("arm64", "x86_64"):
            out = Path(tmp) / arch
            run("swiftc", "-O", "-target", f"{arch}-apple-macos{MIN_MACOS}", src, "-o", out)
            outs.append(out)
        run("lipo", "-create", *outs, "-output", macos_dir / EXECUTABLE)


def sign(app: Path, require_identity: bool = False) -> str:
    """Sign with the project's self-signed identity so macOS keeps remembering
    the app's permissions (Full Disk Access, folder access) across updates, and
    so the updater can tell a genuine build. Without the identity (e.g. a build
    without the secret) it signs ad hoc, unless require_identity is set."""
    identity = "-"
    keychain = None
    p12_b64 = os.environ.get(IDENTITY_ENV, "").strip()
    if not p12_b64 and require_identity:
        raise SystemExit(f"{IDENTITY_ENV} isn't set; refusing to publish an unsigned build")
    if p12_b64:
        import base64
        tmpdir = Path(tempfile.mkdtemp())
        p12 = tmpdir / "identity.p12"
        p12.write_bytes(base64.b64decode(p12_b64))
        keychain = tmpdir / "mac-cleaner-build.keychain-db"
        pw = "build"
        try:
            run("security", "create-keychain", "-p", pw, keychain)
            run("security", "set-keychain-settings", keychain)
            run("security", "unlock-keychain", "-p", pw, keychain)
            run("security", "import", p12, "-k", keychain, "-P", IDENTITY_PASSWORD,
                "-T", "/usr/bin/codesign")
            p12.unlink()
            run("security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:", "-s",
                "-k", pw, keychain, stdout=subprocess.DEVNULL)
            # codesign only looks in keychains on the search list.
            current = subprocess.run(["security", "list-keychains", "-d", "user"], capture_output=True,
                                     text=True).stdout.split()
            run("security", "list-keychains", "-d", "user", "-s", keychain,
                *[c.strip('"') for c in current])
            out = subprocess.run(["security", "find-identity", "-p", "codesigning", str(keychain)],
                                 capture_output=True, text=True).stdout
            print(out)
            hashes = [line.split()[1] for line in out.splitlines() if ")" in line and '"' in line]
            if hashes:
                identity = hashes[0]
        except subprocess.CalledProcessError as e:
            if require_identity:
                raise
            print(f"warning: couldn't load the signing identity ({e}); signing ad hoc")
    extra = ["--keychain", str(keychain)] if keychain and identity != "-" else []

    def codesign(path):
        run("codesign", "--force", "--timestamp=none", "-s", identity, *extra, path)

    try:
        for p in sorted((app / "Contents" / "Resources").rglob("*")):
            if is_macho(p):
                codesign(p)
        codesign(app)
    except subprocess.CalledProcessError:
        if identity == "-" or require_identity:
            raise
        print("warning: signing with the project identity failed; signing ad hoc instead")
        identity, extra = "-", []
        for p in sorted((app / "Contents" / "Resources").rglob("*")):
            if is_macho(p):
                codesign(p)
        codesign(app)
    run("codesign", "--verify", "--deep", "--strict", "--verbose=2", app)
    run("codesign", "-dr", "-", app)
    return identity


def package(app: Path, out: Path, version: str) -> list:
    stem = f"Mac-Cleaner-{version}"
    zip_path = out / f"{stem}.zip"
    run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, zip_path)
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "dmg"
        stage.mkdir()
        run("ditto", app, stage / app.name)
        os.symlink("/Applications", stage / "Applications")
        dmg = out / f"{stem}.dmg"
        if dmg.exists():
            dmg.unlink()
        # hdiutil sometimes reports "Resource busy" on CI machines; it passes on retry.
        for attempt in range(6):
            try:
                run("hdiutil", "create", "-volname", APP_NAME, "-srcfolder", stage, "-ov", "-format", "UDZO", dmg)
                break
            except subprocess.CalledProcessError:
                if attempt == 5:
                    raise
                time.sleep(5)
    return [zip_path, dmg]


def build(arm: Path, x86: Path | None, out: Path, native: bool = True, require_identity: bool = False) -> Path:
    version = macclean.__version__
    out.mkdir(parents=True, exist_ok=True)
    app = out / f"{APP_NAME}.app"
    if app.exists():
        shutil.rmtree(app)
    contents = app / "Contents"
    resources = contents / "Resources"
    (contents / "MacOS").mkdir(parents=True)
    resources.mkdir()

    copy_runtime(arm, x86, resources / "python", native)
    shutil.copytree(ROOT / "macclean", resources / "app" / "macclean",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    write_info_plist(app, version)
    build_icon(resources, native)
    if not native:
        return app

    build_shell(contents / "MacOS")
    py = resources / "python" / "bin" / "python3"
    # Precompile so start-up is fast; the app never writes into its own bundle.
    run(py, "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "unchecked-hash",
        resources / "python" / "lib" / "python3.12", resources / "app")
    env = {**os.environ, "PYTHONPATH": str(resources / "app"), "PYTHONHOME": str(resources / "python")}
    got = subprocess.run([str(py), "-c", "import macclean.server, macclean; print(macclean.__version__)"],
                         env=env, capture_output=True, text=True)
    if got.stdout.strip() != version:
        raise SystemExit(f"Bundled engine failed to start: {got.stderr}")
    print("signed with:", sign(app, require_identity))
    return app


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", type=Path, required=True)
    ap.add_argument("--x86", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "build")
    ap.add_argument("--assemble-only", action="store_true")
    ap.add_argument("--require-identity", action="store_true", help="fail rather than sign ad hoc")
    a = ap.parse_args()
    app = build(a.arm, a.x86, a.out, native=not a.assemble_only, require_identity=a.require_identity)
    if not a.assemble_only:
        for p in package(app, a.out, macclean.__version__):
            print(p)


if __name__ == "__main__":
    main()
