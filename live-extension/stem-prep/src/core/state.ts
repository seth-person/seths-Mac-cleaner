// What "Get ready" changed, saved before anything is changed, so "Put things
// back" works even after Live crashed or was quit in between.

import type { DeviceInfo } from "./types.ts";

export const ACTIVE_RUN_FILE = "active-run.json";
export const STATE_FORMAT = 1;

export interface SavedDevice {
  index: number;
  name: string;
  /** Always true today: only devices that were on get switched off. */
  was_on: boolean;
}

export interface ActiveRun {
  format: number;
  created_at: string;
  song: string;
  record_file: string;
  devices: SavedDevice[];
}

/** The ticked devices that are currently on. Devices already off are left alone. */
export function devicesToSwitchOff(devices: DeviceInfo[], ticked: number[]): SavedDevice[] {
  const wanted = new Set(ticked);
  return devices
    .filter((d) => d.on === true && wanted.has(d.index))
    .map((d) => ({ index: d.index, name: d.name, was_on: true }));
}

export function isActiveRun(value: unknown): value is ActiveRun {
  if (!value || typeof value !== "object") return false;
  const v = value as Partial<ActiveRun>;
  return (
    v.format === STATE_FORMAT &&
    typeof v.created_at === "string" &&
    typeof v.song === "string" &&
    Array.isArray(v.devices) &&
    v.devices.every(
      (d) => d && typeof d.index === "number" && typeof d.name === "string" && typeof d.was_on === "boolean",
    )
  );
}
