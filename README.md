# Mac Cleaner

A Mac app for keeping a Mac tidy. It shows where your disk space goes, sorts out the catch-all
folders (Downloads, Desktop), finds safe things to delete, and keeps your Ableton projects in one
place without breaking them.

It runs entirely on your Mac and never deletes anything. "Trash" moves items to your Trash, and
every action can be undone from the History tab.

## Install

**Already using the browser version (0.2.x)?** Click **Update** in it, then **Get the Mac app**.
That installs the app into Applications, opens it, and removes the old launcher. Your settings,
scans and history carry over, and macOS won't show any security prompts.

**New install:**

1. Open the [latest release](https://github.com/seth-person/seths-Mac-cleaner/releases/latest)
   and download **Mac-Cleaner-x.y.z.dmg**.
2. Open the .dmg and drag **Mac Cleaner** onto **Applications**.
3. Open Mac Cleaner. The first time, macOS says it can't verify the developer, because the app
   isn't registered with Apple (that costs $99/year). Click **Done**, then go to
   System Settings → Privacy & Security, scroll down, and click **Open Anyway** next to
   Mac Cleaner. This happens only once; updates never ask again.

Prefer Terminal? This installs the same app and skips the step-3 warning:

```bash
curl -fsSL https://github.com/seth-person/seths-Mac-cleaner/releases/latest/download/install.sh | bash
```

The app has everything it needs built in (including its own Python), and it runs on Apple
Silicon and Intel Macs with macOS 12 or later.

### Updates

When a new version is out, an **Update to x.y.z** button appears in the top bar. Click it and
Mac Cleaner downloads the new version, checks it isn't corrupted and that it starts, then closes
and reopens itself on the new version. Your settings, scans and history stay put.
**Mac Cleaner → Check for Updates…** (or **Version · Updates**, bottom left) checks straight away
and can **roll back** to the version before.

If macOS blocks the update ("Mac Cleaner was prevented from modifying apps"), the app keeps the
version you had and says so. Allow it under System Settings → Privacy & Security →
**App Management**, then update again.

An update is only installed if it's signed with Mac Cleaner's signing certificate (see
`macos/signing/`).

### First scan

Press **Scan now**. *Home folder* takes a minute or two; *Entire disk* also counts apps and macOS.
macOS asks once whether Mac Cleaner may access Desktop, Documents and Downloads. Say **Allow**.

For the complete picture, give it **Full Disk Access**: System Settings → Privacy & Security →
Full Disk Access → **+** → Mac Cleaner, then quit and reopen it. Every version is signed with the
same identity (see `macos/signing/`), so macOS remembers these permissions across updates.

### Running from source

`python3 -m macclean` runs the same dashboard from a checkout, in your browser. That copy
doesn't update itself. The Updates panel offers to install the app instead.

## What's in the dashboard

| Tab | What it does |
|---|---|
| **Overview** | Disk usage, space by type of file, biggest folders and files, and counts of what needs attention. **Survey report** gives a text summary you can paste into Claude to get folders and rules designed around your actual files. |
| **Explore** | A drillable treemap of any folder from the scan. Toggle between space used *on this Mac* and *including iCloud-only* files. Select items to move or trash them. |
| **Catch-alls** | Every loose item in Downloads and Desktop with its type, size, age and a suggested destination from your rules. Change any suggestion, tick the boxes, and apply. Desktop counts as an *active workspace*, so its items are left alone until they haven't been touched for 21 days. |
| **Cleanup** | Things you probably don't need: app caches, unfinished downloads, zips you've already unzipped, duplicates, Ableton auto-backups, `.asd` files and Live's temporary recordings. Each is marked **Safe** (rebuilt automatically, or an exact copy of something you keep) or **Check first**. It never suggests anything an Ableton set uses, anything inside a project or a sound library (Packs, User Library, Splice, Kontakt…), or your app data folders. Big old files are listed for information only. |
| **Ableton** | **Recent**: projects in the order Live last opened them (read from Live's settings; falls back to last saved). **Important**: projects you've starred, least recently touched first. **Collect All**: every project that uses files from outside its folder or has missing ones, with Show in Finder and a Re-check button. **All projects**: where each lives, whether it's self-contained, and moving into status buckets inside `iCloud Drive/Ableton Projects`. **Factory Packs**: each installed Pack and which sets and presets (including User Library racks) use it. Each project has a checklist: **self-contained**, **has a master**, **has stems**, with where Mac Cleaner found the ones that aren't in the project yet (stems are recognised from Stem Prep's run records, or as files exported together). Every project lists each set in its folder (not the Backup copies) with its own status, an **Open in Live** button, a play button for its newest export (matched by name, e.g. “Song V3.wav” or “Song (MASTER).wav”), and **What's in it**: every export of the song and every audio file the set uses, each playable. |
| **Plan** | Pick any folder and see where everything in it would go, and why: projects into status folders, a song's masters, bounces and stems into its project's `Exports` folder, documents into School, Money and year folders. Each suggestion says how sure it is (Sure, Likely, Guess) and what's stopping it (needs Collect All, used by a set elsewhere). Tick, change and save your choices, then **Preview batch** to see exactly what would move. Preview only for now. Also where you set up your **library**: the one folder your music lives in, so it can move as a whole later. |
| **Rules** | The rules behind the suggestions, editable as JSON (stored in `~/.macclean/config.json`). |
| **History** | Every move and trash. Changes made together are one batch with **Undo all**; a batch that was interrupted (the app or the Mac stopped) can be finished or put back. |

## How it works out what things are

- **Type**: by file extension. Files with no extension or an unknown one are identified from
  their first bytes (PDF, PNG/JPEG, ZIP, WAV/AIFF, MP3, MP4/MOV, installer packages). Folders
  take the type that makes up most of their contents, so a folder of WAVs is a sample pack.
  Packages such as `.app`, `.logicx` and `.vst3` count as one item.
- **Where the space goes**: anything under `~/Library` counts as *app data* (except iCloud Drive
  and cloud-storage folders, which live there but are your files). `/System`, `/usr` and similar
  count as *macOS & system*.
- **iCloud**: files evicted by "Optimise Mac Storage" still report their full size but take no
  space locally. The scanner records both figures, never reads evicted files (reading would
  download them), and leaves them out of duplicate checks.
- **Duplicates**: files of 1 MB or more are grouped by size, then by a hash of their first and
  last 64 KB, then confirmed with a full hash. The copy outside Downloads/Desktop is the one kept.

## Ableton projects

The scanner treats a folder containing `Ableton Project Info` as a project and reads every
`.als` set (gzipped XML) to check each sample and device file it references:

- **Self-contained**: everything it uses is inside the project folder, so it can be moved freely.
- **Outside project**: it uses files somewhere else, such as a sample still in Downloads. Moving
  either one can break the set. Open it in Live and run *File → Collect All and Save* first.
- **Missing**: Live won't find some files even now.

The check skips references Live doesn't need for playback, such as the original source of a
sample or the preset a device was loaded from. Factory Packs and Core Library sounds count as
fine. It also catches the reverse problem: if a file in Downloads is used by a set somewhere
else, Catch-alls flags it and Cleanup won't suggest deleting it.

Projects that look like copies of each other (same name in two places) are flagged too.

## The suggested layout

These are starting defaults, all changeable in Rules:

```
iCloud Drive/
├── Ableton Projects/
│   ├── Active/        what you're working on (instead of the Desktop)
│   ├── Ideas/         sketches and loose sets
│   ├── Finished/      released or bounced
│   └── Archive/       old or abandoned
├── Music/
│   ├── Samples/           sample packs
│   ├── Releases/          finished masters (“… (MASTER 24-bit 48k).wav”)
│   ├── Bounces/2026/      your versioned bounces (“Song V10.wav”)
│   ├── Bounces/Stems & Sketches/2026/   other audio: pieces, stems
│   ├── Samples/Source Tracks/   downloaded FLAC tracks for sampling
│   ├── Ableton Library/   .adg/.adv/.alp presets and packs
│   └── Plugin Installers/
├── Documents/2026/
├── Pictures/2026/
├── Videos/2026/
└── Archives/2026/
```

Tip: in Finder, right-click `Ableton Projects/Active` and choose **Keep Downloaded**. Otherwise
"Optimise Mac Storage" can move samples to the cloud and Live will show them as missing until
they download again.

## Rules

Each rule has a `when` (any of `category`, `ext`, `kind`, `name_regex`, `older_than_days`,
`larger_than_mb`) and an action: `move` (with a `dest`), `trash`, or `keep`. The first matching rule
wins. Destinations can use `{cloud}`, `{ableton}`, `{home}`, `{year}`, `{month}` and `{category}`.

Categories: `audio ableton video image document app archive code installer plugin other`.
Kinds: `file folder ableton-project package`.

## Automating it

Rules marked `"auto": true` can run without the dashboard:

```bash
python3 -m macclean autosort           # show what it would do
python3 -m macclean autosort --apply   # do it
```

To run it every morning, save this as `~/Library/LaunchAgents/com.macclean.autosort.plist`
(fix the path), then run `launchctl load ~/Library/LaunchAgents/com.macclean.autosort.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.macclean.autosort</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>-m</string><string>macclean</string>
    <string>autosort</string><string>--apply</string></array>
  <key>WorkingDirectory</key><string>/Users/YOU/seths-Mac-cleaner</string>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>9</integer></dict>
</dict></plist>
```

No rules are automatic by default. Turn them on only once the suggestions look right.

## Releasing a new version

1. Bump `__version__` in `macclean/__init__.py`.
2. Add a `## <version>` section to `CHANGELOG.md`. It becomes the notes shown in the app.
3. Commit and push to the default branch.

When the version changes, the Release workflow runs the tests, builds the app on a macOS machine
(`macos/build_app.py`: Swift shell + bundled universal Python + signing), launches it to make
sure it starts, then publishes the `.dmg` (first install), `.zip` (in-app updates), a code
tarball (for 0.2.x browser installs to update from), and `SHA256SUMS`. Installed apps pick it up
on their next check.

The app is a small native window (`macos/MacCleaner.swift`, WebKit) around the same Python
engine and dashboard. To build it yourself on a Mac:

```bash
uv python install cpython-3.12.13-macos-aarch64-none cpython-3.12.13-macos-x86_64-none --install-dir /tmp/py
python3 macos/build_app.py --arm /tmp/py/cpython-3.12.13-macos-aarch64-none --x86 /tmp/py/cpython-3.12.13-macos-x86_64-none
```

## Other commands

```bash
python3 -m macclean scan [folders…]   # scan from the terminal (use / for the whole disk)
python3 -m macclean survey            # rewrite ~/.macclean/survey.md from the last scan
python3 -m unittest discover -s tests # run the tests
python3 tests/fixture.py /tmp/demo && HOME=/tmp/demo python3 -m macclean   # try it on a fake messy home
```

## Safety

- The app's engine only listens on 127.0.0.1. Any request that changes files needs a token generated
  each time it starts, so other websites can't trigger actions.
- Only files inside your home folder can be moved or trashed. Top-level folders (Desktop,
  Downloads, iCloud Drive, ~/Library and so on) can't be moved at all.
- Moves never overwrite: a name clash gets " 2" added.
- Everything lands in `~/.macclean/actions.jsonl`, which is what Undo uses.
