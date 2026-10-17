# Mac Cleaner

Stdlib-only Python plus a vanilla JS dashboard in `macclean/static/`, shipped as a macOS app: `macos/MacCleaner.swift` (a native WebKit window) runs the engine using a Python runtime bundled by `macos/build_app.py`. No third-party Python dependencies. Keep the engine compatible with Python 3.9: older browser-based installs run on macOS's /usr/bin/python3 and update via the code tarball.

- Tests: `python3 -m unittest discover -s tests`
- Try it on fake data: `python3 tests/fixture.py /tmp/demo && HOME=/tmp/demo python3 -m macclean`

## Releasing (the user installs from releases and updates in-app)

Every user-facing change ships as a release, so the user gets it through the app's Update button:

1. Bump `__version__` in `macclean/__init__.py` (semver).
2. Add a `## <version>` section at the top of `CHANGELOG.md`, written for the user. It's shown in the app's update dialog.
3. Commit and push to the default branch. `.github/workflows/release.yml` sees the version change, runs the tests, builds and launch-tests the app on macOS (`build-app.yml`), then tags and publishes `v<version>`. Check that the workflow passed. Tag pushes aren't needed (and are blocked from cloud sessions).

Changes to `macos/` trigger `build-app.yml` by itself. Get that green before bumping the version. The build can't be tested locally (Linux), and its artifact has a screenshot of the launched app.

Never publish a release whose tests fail. The updater refuses a build that fails to import, but don't rely on that.

## Signing

Release builds are signed with a key held only in the `MACOS_SIGNING_P12_BASE64` Actions secret. Its certificate is pinned in `macclean/updater.py` (`SIGNING_CERT_SHA1`), and installed apps reject updates not signed with it. Never commit a private key; the repo is public. See `macos/signing/README.md` before touching any of this.
