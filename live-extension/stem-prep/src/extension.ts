import {
  AudioTrack,
  initialize,
  MidiTrack,
  type ActivationContext,
  type ArrangementSelection,
  type Device,
  type DeviceParameter,
  type ExtensionContext,
  type Track,
} from "@ableton-extensions/sdk";

import { renderDialog, type DialogView } from "./core/dialog.ts";
import { getReady, putBack, type LiveAdapter } from "./core/flows.ts";
import { EXTENSION_VERSION } from "./core/record.ts";
import { Store } from "./core/store.ts";
import type { DeviceInfo, TrackInfo, TrackKind } from "./core/types.ts";

// esbuild inlines this page as a string.
import dialogHtml from "./ui/dialog.html";

type Context = ExtensionContext<"1.0.0">;

const CMD_READY = "stem-prep.get-ready";
const CMD_PUT_BACK = "stem-prep.put-back";

/** Every Live device has this parameter; it's the device's on/off switch. */
function onSwitch(device: Device<"1.0.0">): DeviceParameter<"1.0.0"> | null {
  return device.parameters.find((p) => p.name === "Device On") ?? null;
}

async function readOn(device: Device<"1.0.0">): Promise<boolean | null> {
  const param = onSwitch(device);
  if (!param) return null;
  return (await param.getValue()) > (param.min + param.max) / 2;
}

function trackInfo(track: Track<"1.0.0">, kind: TrackKind): TrackInfo {
  return { name: track.name, kind, muted: track.mute, inGroup: track.groupTrack?.name ?? "" };
}

function liveAdapter(context: Context): LiveAdapter {
  const song = () => context.application.song;

  return {
    async snapshot() {
      const s = song();
      // Group tracks come through as AudioTrack, so spot them as the parent of another track.
      const groupIds = new Set(s.tracks.flatMap((t) => (t.groupTrack ? [t.groupTrack.handle.id] : [])));
      const tracks = [
        ...s.tracks.map((t) =>
          trackInfo(
            t,
            groupIds.has(t.handle.id) ? "group" : t instanceof MidiTrack ? "midi" : t instanceof AudioTrack ? "audio" : "group",
          ),
        ),
        ...s.returnTracks.map((t) => trackInfo(t, "return")),
      ];
      const mainDevices: DeviceInfo[] = await Promise.all(
        s.mainTrack.devices.map(async (d, index) => ({ index, name: d.name, on: await readOn(d) })),
      );
      return { tracks, mainDevices, tempo: s.tempo };
    },

    async setMainDevicesOn(indices, on) {
      const devices = song().mainTrack.devices;
      const targets = indices.flatMap((i) => {
        const device = devices[i];
        const param = device && onSwitch(device);
        return param ? [{ device, param }] : [];
      });
      // One undo step for the whole change.
      await context.withinTransaction(() =>
        Promise.allSettled(targets.map(({ param }) => param.setValue(on ? param.max : param.min))),
      );
      const failed: string[] = [];
      for (const i of indices) {
        const device = devices[i];
        if (!device || (await readOn(device)) !== on) failed.push(device ? device.name : `device ${i + 1}`);
      }
      return failed;
    },

    showDialog(view: DialogView) {
      const height = view.mode === "prepare" ? 620 : 300;
      const url = `data:text/html,${encodeURIComponent(renderDialog(dialogHtml, view))}`;
      return context.ui.showModalDialog(url, 520, height).catch(() => "");
    },

    now: () => new Date(),
  };
}

export function activate(activation: ActivationContext) {
  const context = initialize(activation, "1.0.0");
  const storageDir = context.environment.storageDirectory;
  console.log(`Stem Prep ${EXTENSION_VERSION}: storage folder is ${storageDir ?? "(not provided)"}`);
  const adapter = liveAdapter(context);

  const run = (task: (store: Store) => Promise<unknown>) => {
    (async () => {
      if (!storageDir) throw new Error("Live didn't give Stem Prep a storage folder.");
      await task(new Store(storageDir));
    })().catch(async (error: unknown) => {
      console.error("Stem Prep failed:", error);
      await adapter
        .showDialog({
          mode: "message",
          title: "Stem Prep ran into a problem",
          lines: [String(error instanceof Error ? error.message : error), "Nothing else was changed."],
        })
        .catch(() => undefined);
    });
  };

  context.commands.registerCommand(CMD_READY, (arg: unknown) => {
    const selection = arg as ArrangementSelection;
    run((store) =>
      getReady(adapter, store, {
        startBeats: selection.time_selection_start,
        endBeats: selection.time_selection_end,
      }),
    );
  });
  context.commands.registerCommand(CMD_PUT_BACK, () => run((store) => putBack(adapter, store)));

  // Live lists these under Extensions as "Stem Prep: <title>".
  for (const scope of ["AudioTrack.ArrangementSelection", "MidiTrack.ArrangementSelection"] as const) {
    void context.ui.registerContextMenuAction(scope, "Get ready", CMD_READY);
    void context.ui.registerContextMenuAction(scope, "Put things back", CMD_PUT_BACK);
  }
  for (const scope of ["AudioTrack", "MidiTrack"] as const) {
    void context.ui.registerContextMenuAction(scope, "Put things back", CMD_PUT_BACK);
  }
}
