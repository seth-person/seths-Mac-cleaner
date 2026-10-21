// Data passed into the dialog page, and checking what comes back from it.

import type { DeviceInfo, Range, TrackInfo } from "./types.ts";

export const DATA_PLACEHOLDER = "__STEM_PREP_DATA__";

export interface PrepareView {
  mode: "prepare";
  rangeLabel: string;
  lengthLabel: string;
  tracks: TrackInfo[];
  devices: { index: number; name: string; on: boolean | null }[];
  song: string;
  storageDir: string;
}

export interface MessageView {
  mode: "message";
  title: string;
  lines: string[];
}

export type DialogView = PrepareView | MessageView;

export interface PrepareChoice {
  song: string;
  switchOff: number[];
}

/** Bar.beat position, counting bars in 4/4 (the SDK doesn't expose the time signature). */
export function barLabel(beats: number): string {
  const bar = Math.floor(beats / 4) + 1;
  const beat = Math.floor(beats - (bar - 1) * 4) + 1;
  return `${bar}.${beat}`;
}

export function rangeLabels(range: Range): { rangeLabel: string; lengthLabel: string } {
  const beats = range.endBeats - range.startBeats;
  const seconds = range.tempo > 0 ? (beats * 60) / range.tempo : 0;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds - m * 60);
  const bars = beats / 4;
  const barsText = Number.isInteger(bars) ? String(bars) : bars.toFixed(2);
  return {
    rangeLabel: `Bar ${barLabel(range.startBeats)} to ${barLabel(range.endBeats)}`,
    lengthLabel: `${barsText} bars, ${m}:${String(s).padStart(2, "0")} at ${Math.round(range.tempo * 100) / 100} BPM`,
  };
}

export function prepareView(args: {
  range: Range;
  tracks: TrackInfo[];
  devices: DeviceInfo[];
  song: string;
  storageDir: string;
}): PrepareView {
  return {
    mode: "prepare",
    ...rangeLabels(args.range),
    tracks: args.tracks,
    devices: args.devices.map((d) => ({ index: d.index, name: d.name, on: d.on })),
    song: args.song,
    storageDir: args.storageDir,
  };
}

/** Puts the view into the page so it needs no network or files. */
export function renderDialog(html: string, view: DialogView): string {
  // Escaping "<" keeps track names like "</script>" from breaking the page.
  const json = JSON.stringify(view).replace(/</g, "\\u003c");
  return html.replace(DATA_PLACEHOLDER, () => json);
}

/** Returns null when the dialog was cancelled or sent something unexpected. */
export function parsePrepareChoice(raw: string): PrepareChoice | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!value || typeof value !== "object") return null;
  const v = value as { ok?: unknown; song?: unknown; switchOff?: unknown };
  if (v.ok !== true || typeof v.song !== "string" || !Array.isArray(v.switchOff)) return null;
  const song = v.song.trim();
  if (!song) return null;
  const switchOff = v.switchOff.filter((n): n is number => Number.isInteger(n) && n >= 0);
  return { song, switchOff };
}
