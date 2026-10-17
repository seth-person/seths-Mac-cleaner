# Mac Cleaner

A local dashboard for keeping a Mac tidy. It shows where your disk space goes, sorts out
the catch-all folders (Downloads, Desktop), finds safe things to delete, and keeps your Ableton
projects in one place without breaking them.

It runs entirely on your Mac, needs nothing beyond the Python 3 that comes with macOS
developer tools, and never deletes anything. "Trash" moves items to your Trash, and every
action can be undone from the History tab.

## Run it

```bash
git clone https://github.com/seth-person/seths-Mac-cleaner.git
cd seths-Mac-cleaner
python3 -m macclean            # opens http://127.0.0.1:8765
```

Or double-click **Mac Cleaner.command** in Finder.

Then press **Scan now**. *Home folder* takes a minute or two; *Entire disk* also counts apps and
macOS. If `python3` asks to install the command line developer tools, say yes.

**Full Disk Access:** macOS hides some folders (Mail, Messages, parts of ~/Library) from apps
that don't have permission. To see everything, add Terminal under System Settings → Privacy &
Security → Full Disk Access, then restart Terminal. The Overview tells you when folders were
skipped.

## What's in the dashboard

| Tab | What it does |
|---|---|
| **Overview** | Disk usage, space by type of file, biggest folders and files, and counts of what needs attention. **Survey report** gives a text summary you can paste into Claude to get folders and rules designed around your actual files. |
| **Explore** | A drillable treemap of any folder from the scan. Toggle between space used *on this Mac* and *including iCloud-only* files. Select items to move or trash them. |
| **Catch-alls** | Every loose item in Downloads and Desktop with its type, size, age and a suggested destination from your rules. Change any suggestion, tick the boxes, and apply. Desktop counts as an *active workspace*, so its items are left alone until they haven't been touched for 21 days. |
| **Cleanup** | App caches, installers you've already used, interrupted downloads, zips you've already extracted, duplicate files, old screenshots, Ableton auto-backups and `.asd` files, and big files untouched for 6+ months. Each one is marked **Safe** or **Review**. |
| **Music** | Every Ableton project on the Mac, where it lives, and whether it's self-contained. You can move projects into status buckets inside `iCloud Drive/Ableton Projects`. |
| **Rules** | The rules behind the suggestions, editable as JSON (stored in `~/.macclean/config.json`). |
| **History** | Every move and trash, each with an Undo button. |

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
│   ├── Bounces/2026/      mixdowns and masters
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

## Other commands

```bash
python3 -m macclean scan [folders…]   # scan from the terminal (use / for the whole disk)
python3 -m macclean survey            # rewrite ~/.macclean/survey.md from the last scan
python3 -m unittest discover -s tests # run the tests
python3 tests/fixture.py /tmp/demo && HOME=/tmp/demo python3 -m macclean   # try it on a fake messy home
```

## Safety

- The server only listens on 127.0.0.1. Any request that changes files needs a token generated
  each time it starts, so other websites can't trigger actions.
- Only files inside your home folder can be moved or trashed. Top-level folders (Desktop,
  Downloads, iCloud Drive, ~/Library and so on) can't be moved at all.
- Moves never overwrite: a name clash gets " 2" added.
- Everything lands in `~/.macclean/actions.jsonl`, which is what Undo uses.
