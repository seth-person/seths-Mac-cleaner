// Reading and writing JSON in the extension's own storage folder. Nothing
// here touches any path outside the folder it's given.

import { mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

export class Store {
  readonly dir: string;

  constructor(dir: string) {
    this.dir = dir;
  }

  path(...parts: string[]): string {
    return join(this.dir, ...parts);
  }

  /** The parsed file, or null if it doesn't exist or isn't valid JSON. */
  async readJson(...parts: string[]): Promise<unknown> {
    try {
      return JSON.parse(await readFile(this.path(...parts), "utf8"));
    } catch {
      return null;
    }
  }

  /** Writes to a temporary file first, so a crash never leaves half a file. */
  async writeJson(value: unknown, ...parts: string[]): Promise<string> {
    const target = this.path(...parts);
    await mkdir(dirname(target), { recursive: true });
    const temp = `${target}.tmp`;
    await writeFile(temp, JSON.stringify(value, null, 2) + "\n", "utf8");
    await rename(temp, target);
    return target;
  }

  async remove(...parts: string[]): Promise<void> {
    try {
      await unlink(this.path(...parts));
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }
}
