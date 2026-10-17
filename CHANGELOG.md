# Changelog

Each `## <version>` section becomes the release notes shown in the app's Update dialog.

## 0.4.1

- Fixed the Terminal installer (`curl … | bash`), which failed on macOS with "Can't find variable: r".

## 0.4.0

- Mac Cleaner now has a new signing key. Updates are only installed if they're signed with it, so nobody else can push a fake update to your Mac.
- Because of the new key, macOS asks once more for permissions you'd already granted (folder access, Full Disk Access). It won't ask again after future updates.
- Installing and updating no longer need a GitHub token once the project is public.

## 0.3.1

- If macOS ever blocks Mac Cleaner from replacing itself during an update, the app now says so when it reopens and tells you which setting to allow (Privacy & Security → App Management). Before, it would quietly keep the old version.
- The app's background engine now always stops when the app does, even after a force quit.

## 0.3.0

- **Mac Cleaner is now a real Mac app**, with its own window, Dock icon and menu bar. No browser, no Terminal, nothing else to install (Python is built in).
- Updates are one click: **Update** in the top bar downloads the new version, checks it, and the app reopens on its own. **Version · Updates** (bottom left, or Mac Cleaner → Check for Updates…) can roll back to the previous version.
- Coming from the browser version? Click **Get the Mac app**. It installs into Applications, carries over your settings, scans and history, and removes the old launcher.
- Works on both Apple Silicon and Intel Macs.

## 0.2.0

- Install Mac Cleaner as a real app with `install.sh`. It lives in ~/Applications and opens from Spotlight.
- Updates from inside the app: when a new version is out, an **Update** button appears in the top bar. You can also roll back to the previous version.
- New "About & updates" panel (bottom left) with the version, an update check, rollback and Quit.

## 0.1.0

- First version: storage overview, folder explorer, Downloads/Desktop triage with rules, cleanup suggestions, Ableton project organiser, undoable actions.
