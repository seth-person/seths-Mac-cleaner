// The run record: one JSON file per "Get ready", read later by Mac Cleaner to
// match the stems Live exported (by time and track names) to this set.

import type { Range, TrackInfo } from "./types.ts";

export const EXTENSION_VERSION = "0.1.0";
export const RECORD_FORMAT = 1;
export const RUNS_DIR = "stem-runs";

export interface RunRecord {
  format: number;
  extension_version: string;
  created_at: string;
  song: string;
  live_version: string | null;
  range: { start_beats: number; end_beats: number; tempo: number; source: Range["source"] };
  tracks: { name: string; kind: TrackInfo["kind"]; muted: boolean; in_group: string }[];
  main_effects_switched_off: string[];
  set_path: string | null;
}

const pad = (n: number, width = 2) => String(Math.trunc(Math.abs(n))).padStart(width, "0");

/** Local time as ISO 8601 with the timezone offset, e.g. 2026-10-21T12:04:05+02:00. */
export function localIsoString(date: Date): string {
  const offset = -date.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
    `${sign}${pad(offset / 60)}:${pad(offset % 60)}`
  );
}

/** YYYYMMDD-HHMMSS in local time. */
export function timeStamp(date: Date): string {
  return (
    `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-` +
    `${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`
  );
}

/** Makes a song name safe to use inside a file name. */
export function safeFileName(song: string): string {
  const cleaned = song
    .replace(/[\/\\:*?"<>|\u0000-\u001f]/g, "-")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^\.+/, "")
    .slice(0, 80)
    .trim();
  return cleaned || "untitled";
}

export function recordFileName(date: Date, song: string): string {
  return `${timeStamp(date)}-${safeFileName(song)}.json`;
}

export function buildRunRecord(args: {
  date: Date;
  song: string;
  range: Range;
  tracks: TrackInfo[];
  switchedOff: string[];
}): RunRecord {
  return {
    format: RECORD_FORMAT,
    extension_version: EXTENSION_VERSION,
    created_at: localIsoString(args.date),
    song: args.song,
    // The SDK exposes neither Live's version nor the set's file path.
    live_version: null,
    range: {
      start_beats: args.range.startBeats,
      end_beats: args.range.endBeats,
      tempo: args.range.tempo,
      source: args.range.source,
    },
    tracks: args.tracks.map((t) => ({ name: t.name, kind: t.kind, muted: t.muted, in_group: t.inGroup })),
    main_effects_switched_off: args.switchedOff,
    set_path: null,
  };
}
