# Stem Prep

An Ableton Live extension that gets a set ready for exporting stems, puts it back afterwards,
and leaves a small record of each run that Mac Cleaner can use to file the stems next to the
right project.

It never saves the set, never changes the mix, clips or tracks, and only writes inside its own
storage folder.

## What it does

**Stem Prep: Get ready** (right-click inside a time selection on an audio or MIDI track, then
**Extensions**)

- Shows the selected section (bars, length, tempo), every track that will export (muted ones
  marked), and the Main track's effects with a tick box each.
- Asks for the song name. It remembers the last name used for a set with the same track names,
  because extensions can't see the set's name.
- On **Get ready**, it saves what it's about to change, switches the ticked Main track effects
  off (one undo step), writes the run record, and tells you the next step:
  *Press ⌘⇧R, choose All Individual Tracks, WAV, Export.*

Live's export window uses the selection as the export range, so the range is already right.

**Stem Prep: Put things back** (right-click a track or a selection, then **Extensions**)

- Switches back on exactly the effects Get ready switched off, and nothing else.
- Anything changed by hand since (switched back on, deleted, renamed) is left alone and listed.
- Works after Live was quit or crashed in between, because what was changed is saved on disk.

Get ready won't run again until Put things back has run, so a device can never be remembered
as "off" by mistake.

### Is switching the Main effects off needed?

Not for the individual track files. Tested in Live 12.4.15 beta: exporting the same track with
the Main track's effects on and off gives identical audio (apart from Live's random dither),
as long as **Include Return and Main Effects** stays **Off** in the export window, which is
the default. Stem Prep switches them off anyway as a safety net. Note that the full-mix file
Live exports alongside the stems is then without the Main effects too.

## Requirements

- Ableton Live 12 Suite **Beta** 12.4.5 or later (the release version doesn't run extensions).
- To build it: Node.js 24.16 or later, and the Extensions SDK zip
  (`extensions-sdk-1.0.0-beta.1.zip`) from the Live beta programme on Centercode.

The SDK's licence doesn't allow passing its files on, so they aren't in this repo. Copy
`ableton-extensions-sdk-1.0.0-beta.1.tgz` and `ableton-extensions-cli-1.0.0-beta.1.tgz` from
the SDK zip into `vendor/` (gitignored).

## Build

```bash
npm install
npm test
npm run package
```

`npm run package` makes `dist/stem-prep.ablx`.

## Install

1. In Live Beta, open **Live → Settings… → Extensions**.
2. Click **Choose file** (or drag `stem-prep.ablx` onto the page) and confirm.
3. Restart Live.

To update, click **Uninstall** next to Stem Prep first (its saved records are kept), install
the new file, and restart Live.

## Where it writes

Only to its storage folder:

```
~/Library/Application Support/Ableton/Extensions Data/seth-person.stem-prep/
├── stem-runs/<YYYYMMDD-HHMMSS>-<song>.json   one run record per Get ready
├── active-run.json                            what to put back (only while a run is open)
└── song-names.json                            last song name per set of track names
```

### Run record

```json
{
  "format": 1,
  "extension_version": "0.1.0",
  "created_at": "2026-10-21T12:17:56-07:00",
  "song": "My Song",
  "live_version": null,
  "range": { "start_beats": 84, "end_beats": 132, "tempo": 128, "source": "selection" },
  "tracks": [
    { "name": "DRUMS", "kind": "group", "muted": false, "in_group": "" },
    { "name": "1-Kick", "kind": "audio", "muted": false, "in_group": "DRUMS" }
  ],
  "main_effects_switched_off": ["Audio Effect Rack"],
  "set_path": null
}
```

`tracks` lists regular tracks in set order, then return tracks. "All Individual Tracks"
exports one file per entry (muted tracks included) plus the full mix, named
`<name typed in the export window> <track name>.wav` and `<name>.wav`. The file name uses
the track's real name, which can differ slightly from what the export window shows
(underscores show as spaces there).

## Limits

- Extensions can't set the selection, loop or locators, or start an export, so you select the
  section and press ⌘⇧R yourself.
- The SDK can't see the set's name or file path, or Live's version, so `set_path` and
  `live_version` are always `null`.
- Bars are counted in 4/4 in the dialog (the time signature isn't visible to extensions).
  The record stores beats, which are exact.
- Sidechain routing isn't visible to extensions.
- Device on/off uses each device's "Device On" switch. Devices without one are shown but
  can't be ticked.
- A device is found again by its position and name. If several Main devices share a name and
  were moved around, Put things back may not find it and will say so.
