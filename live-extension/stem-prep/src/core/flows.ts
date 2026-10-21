// The two commands, written against a small adapter so tests can stand in
// for Live. extension.ts provides the real adapter.

import { parsePrepareChoice, prepareView, type DialogView } from "./dialog.ts";
import { buildRunRecord, localIsoString, recordFileName, RUNS_DIR } from "./record.ts";
import { describeRestore, planRestore } from "./restore.ts";
import { lookupSongName, rememberSongName, SONG_NAMES_FILE, trackFingerprint, type SongNameMemory } from "./songNames.ts";
import { ACTIVE_RUN_FILE, devicesToSwitchOff, isActiveRun, STATE_FORMAT, type ActiveRun } from "./state.ts";
import type { Store } from "./store.ts";
import type { Range, SetSnapshot } from "./types.ts";

export const NEXT_STEP = "Press ⌘⇧R, choose All Individual Tracks, WAV, Export.";
export const KEEP_OFF_HINT = 'Leave "Include Return and Main Effects" Off in the export window.';

export interface LiveAdapter {
  snapshot(): Promise<SetSnapshot>;
  /** Switches Main track devices (by chain position) on or off. Returns the names that failed. */
  setMainDevicesOn(indices: number[], on: boolean): Promise<string[]>;
  /** Shows the dialog and resolves with what it sent back ("" if closed). */
  showDialog(view: DialogView): Promise<string>;
  now(): Date;
}

export type Outcome = "cancelled" | "blocked" | "ready" | "restored" | "nothing";

const message = (adapter: LiveAdapter, title: string, lines: string[]) =>
  adapter.showDialog({ mode: "message", title, lines });

export async function getReady(
  adapter: LiveAdapter,
  store: Store,
  selection: { startBeats: number; endBeats: number },
): Promise<Outcome> {
  const previous = await store.readJson(ACTIVE_RUN_FILE);
  if (isActiveRun(previous)) {
    await message(adapter, "Put things back first", [
      `Stem Prep already switched off Main track effects for "${previous.song}" (${previous.created_at}) and hasn't put them back yet.`,
      'Right-click a track and choose Extensions → "Stem Prep: Put things back", then run Get ready again.',
    ]);
    return "blocked";
  }

  if (!(selection.endBeats > selection.startBeats)) {
    await message(adapter, "Select the section first", [
      "Drag across the main section of the song in the Arrangement, then right-click inside the selection.",
    ]);
    return "blocked";
  }

  const snapshot = await adapter.snapshot();
  const range: Range = { ...selection, tempo: snapshot.tempo, source: "selection" };
  const fingerprint = trackFingerprint(snapshot.tracks.map((t) => t.name));
  const memory = ((await store.readJson(SONG_NAMES_FILE)) ?? {}) as SongNameMemory;

  const raw = await adapter.showDialog(
    prepareView({
      range,
      tracks: snapshot.tracks,
      devices: snapshot.mainDevices,
      song: lookupSongName(memory, fingerprint),
      storageDir: store.dir,
    }),
  );
  const choice = parsePrepareChoice(raw);
  if (!choice) return "cancelled";

  const date = adapter.now();
  const createdAt = localIsoString(date);
  const toSwitch = devicesToSwitchOff(snapshot.mainDevices, choice.switchOff);
  const recordFile = recordFileName(date, choice.song);

  // Saved before touching anything, so Put things back works even if Live
  // goes away halfway through.
  const state: ActiveRun = {
    format: STATE_FORMAT,
    created_at: createdAt,
    song: choice.song,
    record_file: `${RUNS_DIR}/${recordFile}`,
    devices: toSwitch,
  };
  if (toSwitch.length > 0) await store.writeJson(state, ACTIVE_RUN_FILE);

  const failed = toSwitch.length > 0 ? await adapter.setMainDevicesOn(toSwitch.map((d) => d.index), false) : [];
  const switchedOff = toSwitch.map((d) => d.name).filter((name) => !failed.includes(name));

  await store.writeJson(
    buildRunRecord({ date, song: choice.song, range, tracks: snapshot.tracks, switchedOff }),
    RUNS_DIR,
    recordFile,
  );
  await store.writeJson(rememberSongName(memory, fingerprint, choice.song, createdAt), SONG_NAMES_FILE);

  const lines = [
    switchedOff.length > 0
      ? `Switched off on the Main track: ${switchedOff.join(", ")}.`
      : "Nothing on the Main track was switched off.",
  ];
  if (failed.length > 0) lines.push(`Couldn't switch off: ${failed.join(", ")}. Please switch them off by hand.`);
  lines.push(`Next: ${NEXT_STEP}`, KEEP_OFF_HINT);
  if (switchedOff.length > 0) {
    lines.push("The full-mix file Live exports alongside the stems will be without these effects too.");
  }
  if (switchedOff.length > 0 || failed.length > 0) {
    lines.push('Afterwards, right-click a track and choose Extensions → "Stem Prep: Put things back".');
  }
  await message(adapter, `Ready to export "${choice.song}"`, lines);
  return "ready";
}

export async function putBack(adapter: LiveAdapter, store: Store): Promise<Outcome> {
  const saved = await store.readJson(ACTIVE_RUN_FILE);
  if (!isActiveRun(saved)) {
    await message(adapter, "Nothing to put back", ["Stem Prep hasn't changed anything that still needs undoing."]);
    return "nothing";
  }

  const snapshot = await adapter.snapshot();
  const actions = planRestore(saved.devices, snapshot.mainDevices);
  const toTurnOn = actions.flatMap((a) => (a.kind === "turn_on" ? [a.index] : []));
  const failed = toTurnOn.length > 0 ? await adapter.setMainDevicesOn(toTurnOn, true) : [];

  // Keep the saved state if something failed, so Put things back can be tried again.
  if (failed.length === 0) await store.remove(ACTIVE_RUN_FILE);

  const lines = describeRestore(actions, failed);
  if (failed.length > 0) lines.push("You can run Put things back again to retry.");
  await message(adapter, `Put back "${saved.song}"`, lines);
  return "restored";
}
