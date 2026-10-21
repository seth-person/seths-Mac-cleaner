import assert from "node:assert/strict";
import { readdir } from "node:fs/promises";
import { afterEach, beforeEach, test } from "node:test";

import { getReady, NEXT_STEP, putBack } from "../src/core/flows.ts";
import { ACTIVE_RUN_FILE } from "../src/core/state.ts";
import type { Store } from "../src/core/store.ts";
import { FakeLive, mainDevices, tempStore, TRACKS } from "./fakes.ts";

const SECTION = { startBeats: 64, endBeats: 128 };

let store: Store;
let cleanup: () => Promise<void>;

beforeEach(async () => {
  ({ store, cleanup } = await tempStore());
});
afterEach(() => cleanup());

const lastLines = (live: FakeLive) => {
  const view = live.shown.at(-1);
  assert.equal(view?.mode, "message");
  return view.mode === "message" ? view.lines.join("\n") : "";
};

test("Get ready switches off the ticked devices and writes the run record", async () => {
  const live = new FakeLive(mainDevices()).choose("My Song", [0, 1]);
  assert.equal(await getReady(live, store, SECTION), "ready");

  assert.deepEqual(live.devices.map((d) => d.on), [false, false, false]);

  const files = await readdir(store.path("stem-runs"));
  assert.deepEqual(files, ["20261021-140509-My Song.json"]);
  const record = (await store.readJson("stem-runs", files[0])) as Record<string, unknown>;
  assert.deepEqual(Object.keys(record).sort(), [
    "created_at", "extension_version", "format", "live_version", "main_effects_switched_off",
    "range", "set_path", "song", "tracks",
  ]);
  assert.equal(record.format, 1);
  assert.equal(record.song, "My Song");
  assert.deepEqual(record.range, { start_beats: 64, end_beats: 128, tempo: 128, source: "selection" });
  assert.deepEqual(record.main_effects_switched_off, ["Mastering Rack", "Limiter"]);
  assert.equal(record.set_path, null);
  assert.deepEqual((record.tracks as unknown[])[2], { name: "2-Hats", kind: "audio", muted: true, in_group: "DRUMS" });
  assert.equal((record.tracks as unknown[]).length, TRACKS.length);

  assert.match(lastLines(live), new RegExp(NEXT_STEP.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
});

test("the dialog shows the section, tracks and devices", async () => {
  const live = new FakeLive(mainDevices());
  live.answers.push(JSON.stringify({ ok: false }));
  assert.equal(await getReady(live, store, SECTION), "cancelled");

  const view = live.shown[0];
  assert.equal(view.mode, "prepare");
  if (view.mode !== "prepare") return;
  assert.equal(view.rangeLabel, "Bar 17.1 to 33.1");
  assert.equal(view.lengthLabel, "16 bars, 0:30 at 128 BPM");
  assert.equal(view.tracks.length, TRACKS.length);
  assert.deepEqual(view.devices.map((d) => d.on), [true, true, false]);
  assert.equal(view.storageDir, store.dir);
});

test("cancelling changes nothing and writes nothing", async () => {
  const live = new FakeLive(mainDevices());
  live.answers.push("");
  assert.equal(await getReady(live, store, SECTION), "cancelled");
  assert.deepEqual(live.devices.map((d) => d.on), [true, true, false]);
  assert.deepEqual(await readdir(store.dir), []);
});

test("an empty selection asks for a selection first", async () => {
  const live = new FakeLive(mainDevices());
  assert.equal(await getReady(live, store, { startBeats: 32, endBeats: 32 }), "blocked");
  assert.equal(live.shown.length, 1);
  assert.match(lastLines(live), /Drag across the main section/);
});

test("a device that was already off is never switched or restored", async () => {
  const live = new FakeLive(mainDevices()).choose("Song", [0, 1, 2]);
  await getReady(live, store, SECTION);
  const state = (await store.readJson(ACTIVE_RUN_FILE)) as { devices: { name: string }[] };
  assert.deepEqual(state.devices.map((d) => d.name), ["Mastering Rack", "Limiter"]);

  await putBack(live, store);
  assert.deepEqual(live.devices.map((d) => d.on), [true, true, false]);
});

test("Put things back restores exactly what Get ready changed", async () => {
  const live = new FakeLive(mainDevices()).choose("Song", [1]);
  await getReady(live, store, SECTION);
  assert.deepEqual(live.devices.map((d) => d.on), [true, false, false]);

  assert.equal(await putBack(live, store), "restored");
  assert.deepEqual(live.devices.map((d) => d.on), [true, true, false]);
  assert.equal(await store.readJson(ACTIVE_RUN_FILE), null);
  assert.match(lastLines(live), /Limiter: switched back on/);
});

test("Put things back works from the saved file alone (Live was quit in between)", async () => {
  const first = new FakeLive(mainDevices()).choose("Song", [0, 1]);
  await getReady(first, store, SECTION);

  // A new Live session: same set reopened unsaved would have everything on,
  // reopened after a save it has the devices off. Test the second case.
  const second = new FakeLive([
    { index: 0, name: "Mastering Rack", on: false },
    { index: 1, name: "Limiter", on: false },
    { index: 2, name: "Spectrum", on: false },
  ]);
  await putBack(second, store);
  assert.deepEqual(second.devices.map((d) => d.on), [true, true, false]);
});

test("Put things back leaves alone what was changed by hand, and says so", async () => {
  const live = new FakeLive(mainDevices()).choose("Song", [0, 1]);
  await getReady(live, store, SECTION);

  live.devices[0].on = true; // switched back on by hand
  live.devices.splice(1, 1); // Limiter deleted

  await putBack(live, store);
  const text = lastLines(live);
  assert.match(text, /Mastering Rack: already on/);
  assert.match(text, /Limiter: no longer on the Main track/);
  assert.equal(await store.readJson(ACTIVE_RUN_FILE), null);
});

test("a device moved to another position is still found by name", async () => {
  const live = new FakeLive(mainDevices()).choose("Song", [1]);
  await getReady(live, store, SECTION);
  live.devices = [
    { index: 0, name: "Limiter", on: false },
    { index: 1, name: "Mastering Rack", on: true },
  ];
  await putBack(live, store);
  assert.deepEqual(live.devices.map((d) => d.on), [true, true]);
});

test("Get ready refuses to run twice before things are put back", async () => {
  const live = new FakeLive(mainDevices()).choose("Song", [0]);
  await getReady(live, store, SECTION);
  live.choose("Song", [1]);
  assert.equal(await getReady(live, store, SECTION), "blocked");
  assert.match(lastLines(live), /Put things back/);
  assert.equal(live.devices[1].on, true);
});

test("switching nothing off leaves no saved state behind", async () => {
  const live = new FakeLive(mainDevices()).choose("Song", []);
  assert.equal(await getReady(live, store, SECTION), "ready");
  assert.equal(await store.readJson(ACTIVE_RUN_FILE), null);
  assert.equal(await getReady(live.choose("Song", []), store, SECTION), "ready");
});

test("a failed switch is reported and kept for a retry", async () => {
  const live = new FakeLive(mainDevices()).choose("Song", [0, 1]);
  await getReady(live, store, SECTION);
  live.stuck.add("Limiter");
  await putBack(live, store);
  assert.match(lastLines(live), /Limiter: couldn't switch it back on/);
  assert.notEqual(await store.readJson(ACTIVE_RUN_FILE), null);

  live.stuck.clear();
  await putBack(live, store);
  assert.equal(live.devices[1].on, true);
  assert.equal(await store.readJson(ACTIVE_RUN_FILE), null);
});

test("Put things back with nothing saved says so", async () => {
  const live = new FakeLive(mainDevices());
  assert.equal(await putBack(live, store), "nothing");
});

test("the song name is remembered for a set with the same tracks", async () => {
  const live = new FakeLive(mainDevices()).choose("Remembered", []);
  await getReady(live, store, SECTION);
  live.answers.push(JSON.stringify({ ok: false }));
  await getReady(live, store, SECTION);
  const view = live.shown.at(-1);
  assert.equal(view?.mode === "prepare" && view.song, "Remembered");
});
