import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { barLabel, parsePrepareChoice, renderDialog } from "../src/core/dialog.ts";
import { EXTENSION_VERSION, localIsoString, recordFileName, safeFileName } from "../src/core/record.ts";
import { lookupSongName, rememberSongName, trackFingerprint } from "../src/core/songNames.ts";
import { devicesToSwitchOff, isActiveRun } from "../src/core/state.ts";
import { tempStore } from "./fakes.ts";

test("record file names use local time and a safe song name", () => {
  const date = new Date(2026, 0, 2, 3, 4, 5);
  assert.equal(recordFileName(date, "Song: A/B?"), "20260102-030405-Song- A-B-.json");
  assert.equal(safeFileName("   "), "untitled");
  assert.equal(safeFileName("..hidden"), "hidden");
  assert.equal(safeFileName("x".repeat(200)).length, 80);
});

test("created_at is ISO 8601 with the timezone offset", () => {
  const iso = localIsoString(new Date(2026, 9, 21, 14, 5, 9));
  assert.match(iso, /^2026-10-21T14:05:09[+-]\d\d:\d\d$/);
  assert.equal(new Date(iso).getTime(), new Date(2026, 9, 21, 14, 5, 9).getTime());
});

test("the version in the code matches manifest.json and package.json", async () => {
  for (const file of ["manifest.json", "package.json"]) {
    const json = JSON.parse(await readFile(new URL(`../${file}`, import.meta.url), "utf8"));
    assert.equal(json.version, EXTENSION_VERSION, file);
  }
});

test("track fingerprints ignore order and notice changes", () => {
  assert.equal(trackFingerprint(["a", "b"]), trackFingerprint(["b", "a"]));
  assert.notEqual(trackFingerprint(["a", "b"]), trackFingerprint(["a", "c"]));
  const memory = rememberSongName({}, "fp", "Song", "now");
  assert.equal(lookupSongName(memory, "fp"), "Song");
  assert.equal(lookupSongName(memory, "other"), "");
});

test("only ticked devices that are on get switched off", () => {
  const devices = [
    { index: 0, name: "A", on: true },
    { index: 1, name: "B", on: false },
    { index: 2, name: "C", on: null },
    { index: 3, name: "D", on: true },
  ];
  assert.deepEqual(devicesToSwitchOff(devices, [0, 1, 2]), [{ index: 0, name: "A", was_on: true }]);
});

test("saved state is checked before use", () => {
  assert.equal(isActiveRun(null), false);
  assert.equal(isActiveRun({ format: 2, created_at: "", song: "", devices: [] }), false);
  assert.equal(isActiveRun({ format: 1, created_at: "", song: "", devices: [{ index: "0" }] }), false);
  assert.equal(isActiveRun({ format: 1, created_at: "", song: "", record_file: "", devices: [] }), true);
});

test("bar labels count from bar 1 in 4/4", () => {
  assert.equal(barLabel(0), "1.1");
  assert.equal(barLabel(4), "2.1");
  assert.equal(barLabel(6.5), "2.3");
});

test("dialog answers are validated", () => {
  assert.deepEqual(parsePrepareChoice('{"ok":true,"song":" S ","switchOff":[0,"1",-1,2]}'), {
    song: "S",
    switchOff: [0, 2],
  });
  assert.equal(parsePrepareChoice(""), null);
  assert.equal(parsePrepareChoice('{"ok":false}'), null);
  assert.equal(parsePrepareChoice('{"ok":true,"song":"  ","switchOff":[]}'), null);
});

test("track names can't break out of the dialog page", () => {
  const page = renderDialog('<script id="data">__STEM_PREP_DATA__</script>', {
    mode: "message",
    title: "</script><b>$&",
    lines: [],
  });
  assert.equal(page.match(/<\/script>/g)?.length, 1);
  assert.ok(page.includes("$&"));
});

test("the dialog page has the data placeholder", async () => {
  const html = await readFile(new URL("../src/ui/dialog.html", import.meta.url), "utf8");
  assert.ok(html.includes("__STEM_PREP_DATA__"));
});

test("the store writes whole files and reads missing ones as null", async () => {
  const { store, cleanup } = await tempStore();
  try {
    assert.equal(await store.readJson("nope.json"), null);
    await store.writeJson({ a: 1 }, "sub", "x.json");
    assert.deepEqual(await store.readJson("sub", "x.json"), { a: 1 });
    await store.remove("sub", "x.json");
    await store.remove("sub", "x.json");
    assert.equal(await store.readJson("sub", "x.json"), null);
  } finally {
    await cleanup();
  }
});
