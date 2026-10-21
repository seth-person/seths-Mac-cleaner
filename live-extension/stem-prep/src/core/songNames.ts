// Remembers the song name last used for a set. The SDK can't see the set's
// name, so a set is recognised by its track names instead.

import { createHash } from "node:crypto";

export const SONG_NAMES_FILE = "song-names.json";

export type SongNameMemory = Record<string, { song: string; used_at: string }>;

/** Same track names in any order give the same fingerprint. */
export function trackFingerprint(trackNames: string[]): string {
  const sorted = [...trackNames].sort();
  return createHash("sha256").update(JSON.stringify(sorted)).digest("hex").slice(0, 16);
}

export function lookupSongName(memory: SongNameMemory, fingerprint: string): string {
  const entry = memory[fingerprint];
  return entry && typeof entry.song === "string" ? entry.song : "";
}

export function rememberSongName(
  memory: SongNameMemory,
  fingerprint: string,
  song: string,
  usedAt: string,
): SongNameMemory {
  return { ...memory, [fingerprint]: { song, used_at: usedAt } };
}
