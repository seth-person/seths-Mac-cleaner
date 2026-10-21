// A stand-in for Live: a set with tracks and Main track devices, and a dialog
// that answers from a queue.

import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import type { DialogView } from "../src/core/dialog.ts";
import type { LiveAdapter } from "../src/core/flows.ts";
import { Store } from "../src/core/store.ts";
import type { DeviceInfo, SetSnapshot, TrackInfo } from "../src/core/types.ts";

export const TRACKS: TrackInfo[] = [
  { name: "DRUMS", kind: "group", muted: false, inGroup: "" },
  { name: "1-Kick", kind: "audio", muted: false, inGroup: "DRUMS" },
  { name: "2-Hats", kind: "audio", muted: true, inGroup: "DRUMS" },
  { name: "3-Bass", kind: "midi", muted: false, inGroup: "" },
  { name: "A-Reverb", kind: "return", muted: false, inGroup: "" },
];

export class FakeLive implements LiveAdapter {
  devices: DeviceInfo[];
  tempo = 128;
  answers: string[] = [];
  shown: DialogView[] = [];
  /** Device names whose switch refuses to move. */
  stuck = new Set<string>();
  date = new Date(2026, 9, 21, 14, 5, 9);

  constructor(devices: DeviceInfo[]) {
    this.devices = devices.map((d) => ({ ...d }));
  }

  async snapshot(): Promise<SetSnapshot> {
    return { tracks: TRACKS, mainDevices: this.devices.map((d) => ({ ...d })), tempo: this.tempo };
  }

  async setMainDevicesOn(indices: number[], on: boolean): Promise<string[]> {
    const failed: string[] = [];
    for (const i of indices) {
      const device = this.devices.find((d) => d.index === i);
      if (!device || device.on === null || this.stuck.has(device.name)) {
        failed.push(device ? device.name : `device ${i + 1}`);
      } else {
        device.on = on;
      }
    }
    return failed;
  }

  async showDialog(view: DialogView): Promise<string> {
    this.shown.push(view);
    return this.answers.shift() ?? JSON.stringify({ ok: true });
  }

  now(): Date {
    return this.date;
  }

  /** Answers the next Get ready dialog. */
  choose(song: string, switchOff: number[]): this {
    this.answers.push(JSON.stringify({ ok: true, song, switchOff }));
    return this;
  }
}

export function mainDevices(): DeviceInfo[] {
  return [
    { index: 0, name: "Mastering Rack", on: true },
    { index: 1, name: "Limiter", on: true },
    { index: 2, name: "Spectrum", on: false },
  ];
}

export async function tempStore(): Promise<{ store: Store; cleanup: () => Promise<void> }> {
  const dir = await mkdtemp(join(tmpdir(), "stem-prep-test-"));
  return { store: new Store(dir), cleanup: () => rm(dir, { recursive: true, force: true }) };
}
