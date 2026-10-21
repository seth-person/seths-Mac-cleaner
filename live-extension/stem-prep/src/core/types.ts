// Plain data shapes the core logic works on. extension.ts builds these from
// the SDK, so everything in core/ can be tested without Live.

export type TrackKind = "audio" | "midi" | "group" | "return";

export interface TrackInfo {
  name: string;
  kind: TrackKind;
  muted: boolean;
  /** Name of the group track this track sits in, or "" if none. */
  inGroup: string;
}

export interface DeviceInfo {
  /** Position in the Main track's device chain. */
  index: number;
  name: string;
  /** null when the device has no "Device On" switch the SDK can see. */
  on: boolean | null;
}

export interface Range {
  startBeats: number;
  endBeats: number;
  tempo: number;
  source: "locators" | "loop" | "selection";
}

export interface SetSnapshot {
  /** Regular tracks first, then return tracks. */
  tracks: TrackInfo[];
  mainDevices: DeviceInfo[];
  tempo: number;
}
