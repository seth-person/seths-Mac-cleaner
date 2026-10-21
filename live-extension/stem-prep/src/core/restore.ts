// Works out how to undo "Get ready" without overwriting anything changed by
// hand since.

import type { SavedDevice } from "./state.ts";
import type { DeviceInfo } from "./types.ts";

export type RestoreAction =
  | { kind: "turn_on"; index: number; name: string }
  | { kind: "already_on"; name: string }
  | { kind: "missing"; name: string }
  | { kind: "no_switch"; name: string };

/**
 * Finds the saved device on the Main track: at the same position with the
 * same name, or else the only device with that name (it was moved).
 */
function findDevice(saved: SavedDevice, current: DeviceInfo[]): DeviceInfo | undefined {
  const atIndex = current.find((d) => d.index === saved.index);
  if (atIndex && atIndex.name === saved.name) return atIndex;
  const sameName = current.filter((d) => d.name === saved.name);
  return sameName.length === 1 ? sameName[0] : undefined;
}

export function planRestore(saved: SavedDevice[], current: DeviceInfo[]): RestoreAction[] {
  return saved
    .filter((s) => s.was_on)
    .map((s): RestoreAction => {
      const device = findDevice(s, current);
      if (!device) return { kind: "missing", name: s.name };
      if (device.on === null) return { kind: "no_switch", name: s.name };
      if (device.on) return { kind: "already_on", name: s.name };
      return { kind: "turn_on", index: device.index, name: device.name };
    });
}

/** Plain-words summary for the dialog, one line per device. */
export function describeRestore(actions: RestoreAction[], failed: string[] = []): string[] {
  if (actions.length === 0) return ["Nothing on the Main track needed switching back on."];
  return actions.map((a) => {
    switch (a.kind) {
      case "turn_on":
        return failed.includes(a.name)
          ? `${a.name}: couldn't switch it back on. Please switch it on by hand.`
          : `${a.name}: switched back on.`;
      case "already_on":
        return `${a.name}: already on, left as it is (switched on by hand, or the set was reopened without saving).`;
      case "missing":
        return `${a.name}: no longer on the Main track, so nothing was changed.`;
      case "no_switch":
        return `${a.name}: its on/off switch can't be reached, please check it by hand.`;
    }
  });
}
