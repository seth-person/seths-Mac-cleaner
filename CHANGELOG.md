# Changelog

Each `## <version>` section becomes the release notes shown in the app's Update dialog.

## 0.7.0

- **Music is now Ableton**, with new tabs:
  - **Recent**: your projects in the order Live last opened them, read from Live's own settings. If Mac Cleaner can't read that list, it goes by when each project was last saved.
  - **Important**: click the ☆ next to any project to star it. Starred projects are listed with the one you haven't touched longest first, so nothing slips through the cracks. Stars follow a project when Mac Cleaner moves it.
  - **Collect All**: every project that uses samples from outside its folder, or has missing ones. Each shows which files are involved.
    - **Show in Finder** takes you to the set. Open it, Collect All and Save, then click **Re-check**: the project drops off the list without a full rescan.
- **Audio in Downloads and Desktop is sorted by how it's named:**
  - **FLAC** files are downloaded tracks → `Music/Samples/Source Tracks`.
  - **MASTER** in capitals, e.g. “Blackout (MASTER 24-bit 48k)”, is a finished song → `Music/Releases`.
  - A **version number**, e.g. “Blackout Remix V10”, is one of your bounces → `Music/Bounces/<year>`.
  - **Anything else** is a stem or sketch → `Music/Bounces/Stems & Sketches/<year>`.
  - The old single “Bounces & audio” rule is replaced. Your other rule changes are kept.

## 0.6.0

- **Presets and racks now count.** Mac Cleaner now reads the racks and presets in your User Library (and anywhere else), not just sets. A Pack or sample that only a rack uses is now protected too: for example, the Drive and Glow samples loaded by [dnksaus] Stock Drum Selecta.
- **New: Factory Packs** (Music → Factory Packs). Each installed Pack shows its size and exactly which sets and presets use it.
  - **Unused** only appears when nothing uses the Pack and every set and preset could be read.
  - Packs that Live lists but that are missing from disk, while something still needs them, are flagged in red.
- **Never moved or trashed**, even from Explore:
  - Live's User Library and its main folders. These have to be moved from inside Live, or projects break.
  - Installed Packs.
  - Anything in your rekordbox folder.
- A file in Downloads or Desktop that a preset loads is kept where it is, with advice on what to do.
- The **Collect All and Save** instructions now say to tick every source: Elsewhere, Other Projects, User Library and Factory Packs.
- **Rescan once after updating** so your presets and racks get checked.

## 0.5.0

Safer cleanup, reviewed in two rounds by an independent reviewer.

- **"Safe" now only means safe:** rebuilt automatically, or an exact copy of something you keep. Installers, most app caches and `.asd` files are **Check first**.
- **Ableton is better protected:** nothing a set uses is ever suggested, including samples inside projects, and Mac Cleaner checks again the moment you click. If some sets are only in iCloud and couldn't be read, it says so and hides audio duplicates rather than guessing.
- **Installers from music-software makers** (Serum, FabFilter, Native Instruments, iZotope…) are filed in Plugin Installers instead of being suggested for the Trash. Old screenshots are filed in Pictures/Screenshots.
- **Zips are only "already unzipped"** when every file in the folder is identical to the zip.
- **Duplicates keep the organised copy** (iCloud, Projects). Catch-alls and Cleanup now agree. It warns you when trashing an iCloud copy would remove it from your other devices.
- **Mac Cleaner won't move or trash app data folders**, Ableton's library, the main folders in iCloud Drive, or Photos and Music libraries, even from Explore.
- **Clearer screens:**
  - The Overview starts with what to do next.
  - "Select N safe items (size)" shows what you're about to select.
  - Confirmations explain each item.
  - After trashing, it tells you the space comes back when you empty the Trash.
  - Rules are plain sentences with on/off switches, and changes can be undone.
- Cleaning up a folder's `.asd` files is now one action you can undo in one click, and they go to a visible folder in the Trash.
- Saved settings now pick up improved default rules automatically.

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
