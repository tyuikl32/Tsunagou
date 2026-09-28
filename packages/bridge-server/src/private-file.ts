import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import {
  closeSync, existsSync, fsyncSync, linkSync, lstatSync, mkdirSync, openSync,
  readFileSync, renameSync, unlinkSync, writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";

let windowsSid: string | undefined;

function restrictFile(path: string): void {
  if (process.platform !== "win32") return;
  windowsSid ??= execFileSync("whoami.exe", ["/user", "/fo", "csv", "/nh"], {
    encoding: "utf8", windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
  }).match(/S-1-\d+(?:-\d+)+/)?.[0];
  if (!windowsSid) throw new Error("private_file_sid_unavailable");
  execFileSync("icacls.exe", [path, "/inheritance:r", "/grant:r", `*${windowsSid}:(F)`], {
    windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
  });
}

/** Restrict the empty temporary file BEFORE writing any secret, then fsync/rename. */
function persistPrivateJson(path: string, value: unknown, createOnly: boolean): boolean {
  const parent = dirname(path);
  let temporary: string | undefined;
  let descriptor: number | undefined;
  try {
    mkdirSync(parent, { recursive: true, mode: 0o700 });
    if (existsSync(path) && lstatSync(path).isSymbolicLink()) {
      throw new Error("private_file_symlink");
    }
    temporary = join(parent, `.tsunagou-private-${randomUUID()}.tmp`);
    descriptor = openSync(temporary, "wx", 0o600);
    restrictFile(temporary);
    writeFileSync(descriptor, JSON.stringify(value, null, 2) + "\n", "utf8");
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = undefined;
    if (createOnly) {
      try {
        // Hard-link an already complete, fsynced, private file. Unlike rename,
        // this atomically fails if a competing bridge created the journal.
        linkSync(temporary, path);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "EEXIST") return false;
        throw error;
      }
      unlinkSync(temporary);
      temporary = undefined;
    } else {
      renameSync(temporary, path);
      temporary = undefined;
    }
    if (process.platform !== "win32") {
      const directory = openSync(parent, "r");
      try { fsyncSync(directory); } finally { closeSync(directory); }
    }
    return true;
  } catch {
    // OS/process exceptions can contain paths or command arguments. Keep the
    // bridge's model-visible diagnostics bounded to a public error code.
    throw new Error("credential_private_save_failed");
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
    if (temporary !== undefined && existsSync(temporary)) unlinkSync(temporary);
  }
}

export function writePrivateJson(path: string, value: unknown): void {
  persistPrivateJson(path, value, false);
}

export function createPrivateJson(path: string, value: unknown): boolean {
  return persistPrivateJson(path, value, true);
}

export function readPrivateJson(path: string): unknown | undefined {
  if (!existsSync(path)) return undefined;
  try {
    if (lstatSync(path).isSymbolicLink()) throw new Error("private_file_symlink");
    return JSON.parse(readFileSync(path, "utf8")) as unknown;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    // A corrupt handoff must not be mistaken for an absent Agent and enroll a
    // second identity. Keep the journal for explicit recovery/diagnosis.
    throw new Error("credential_private_file_invalid");
  }
}
