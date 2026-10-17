# Mac Cleaner

Stdlib-only Python (must stay compatible with Python 3.9, macOS's /usr/bin/python3) plus a vanilla JS dashboard in `macclean/static/`. No third-party dependencies.

- Tests: `python3 -m unittest discover -s tests`
- Try it on fake data: `python3 tests/fixture.py /tmp/demo && HOME=/tmp/demo python3 -m macclean`

## Releasing (the user installs from releases and updates in-app)

Every user-facing change ships as a release, so the user gets it through the app's Update button:

1. Bump `__version__` in `macclean/__init__.py` (semver).
2. Add a `## <version>` section at the top of `CHANGELOG.md`, written for the user. It's shown in the app's update dialog.
3. Commit, push, then `git tag v<version> && git push origin v<version>`.
4. `.github/workflows/release.yml` tests, builds and publishes. Check that the workflow passed.

Never publish a release whose tests fail. The updater refuses a build that fails to import, but don't rely on that.
