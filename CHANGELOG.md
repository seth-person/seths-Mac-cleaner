# Changelog

Each `## <version>` section becomes the release notes shown in the app's Update dialog.

## 0.9.1

- **Fixed: updating could put you back on an older version.** Mac Cleaner keeps a backup copy of the version before, so you can roll back. If that backup was opened instead of the app (for example from Spotlight) and you clicked Update, the old version ended up back in place. The backup copy now refuses to update and tells you to open Mac Cleaner from your Applications folder.
- The backup copy no longer shows up in Spotlight or Launchpad, so it can't be opened by mistake.

## 0.9.0

The first step towards organising your whole Mac. Nothing in this version moves anything new: it adds safety around every move and shows what organising would do, so you can check it on your real folders first.

- **New Plan tab.** Pick any folder (Downloads, Desktop, a projects folder, a folder of stems…) and see where each thing in it would go, and why:
  - Projects go into status folders, guessed from where they are now (“Completed Projects” → Finished).
  - A song's masters, bounces and stems go into its project's `Exports` folder.
  - Each suggestion says how sure it is: **Sure**, **Likely** or **Guess**. Guesses never start ticked.
  - Anything that would break is shown in red and can't be ticked: a project that needs Collect All, or a file a set elsewhere uses.
  - Your changes are saved, so you can work through a long list over several days. **Preview batch** shows exactly what would move. Running it comes in a later version.
- **Set up your library** (in the Plan tab): the one folder your music lives in, and your status folders. Choosing it moves nothing.
- **Every project now has a checklist** in Ableton → All projects: self-contained, has a master, has stems, with where Mac Cleaner found the ones that aren't in the project yet. Filter by Organised, Almost or Needs work. A sketch can be marked “Doesn't need a master”.
- **Stems are recognised**: files Live exported together (“Song Drums.wav”, “Song Bass.wav”…), and runs from the Stem Prep extension for Live. They're matched to their project by name or by track names. **Rescan once** so Mac Cleaner reads your sets' track names.
- **Safer moves everywhere** (Catch-alls, Cleanup, Explore, Ableton):
  - Changes made together are one batch with **Undo all** in History.
  - If the app or the Mac stops in the middle, the next launch says how far it got. You can finish it or put it back.
  - Projects and sets wait until Live is closed. Final Cut libraries wait for Final Cut, rekordbox's folder for rekordbox.
  - Files that are only in iCloud are never moved out of iCloud until they're downloaded.
  - Nothing moves to a different disk.
  - After moving projects, their sets are checked again. If one now misses files, you can put the batch back straight away.
  - Before a big batch, you're reminded if Time Machine hasn't backed up in the last week.
- **Catch-alls** no longer suggests sending a folder of stems to Samples when it belongs to a project. School and money documents (course codes, taxes, 1099s, receipts) get their own suggestions.
- The Ableton tab says when Live's default template file is missing.

## 0.8.0

- **Listen to your sets from Mac Cleaner.** A set file holds no audio of its own, so Mac Cleaner plays audio you already have:
  - **▶ next to each set** plays the newest export of that song. Exports are matched by name wherever they are: “Blackout Remix V10.wav” and “Blackout Remix (MASTER 24-bit 48k).wav” both belong to “Blackout Remix.als”. Sets without one say “no bounce yet”.
  - **What's in it** lists every export of the song, plus every audio file the set uses (samples, recordings, stems), each with a play button.
  - A player bar at the bottom keeps playing while you move around the app. Exports that are only in iCloud download when you play them.

## 0.7.2

- **Each project now lists every set in its folder**, with its own status, when it was last saved and the Live version. Backup copies are left out.
  - When one set has missing files and another doesn't, you can see which one. For example, a project shows “2 missing · 1 of 2 sets”, and the set list underneath points to the set with the problem.
- **Open in Live** next to every set opens it straight from Mac Cleaner. **Show** finds it in Finder.
- **Show in Finder** on a project now shows the project folder.

## 0.7.1

- **Re-check no longer reloads the page.** The button shows a spinner while it reads the project, then updates just that project. You stay where you were on the list.
- **Missing files now say where in the set they're used**, e.g. “in Track “Drums” › Drum Rack › pad “Kick” › Simpler”, so you can find them in Live.
  - Click **Re-check** on a project (or rescan) to get this for sets scanned before this version.
- **New: Copy details** on projects with missing files. It copies exactly what Mac Cleaner found, ready to paste into a message, for when Live says nothing is missing but Mac Cleaner disagrees.
- The Collect All tab explains how to check in Live: File → Manage Files → Manage Set lists any missing files.

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
- The Terminal installer no longer asks for a GitHub token when GitHub is only busy. It now says to wait and try again.

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
