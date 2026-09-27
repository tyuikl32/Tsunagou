import { createHash } from "node:crypto";
import { mkdirSync, realpathSync } from "node:fs";
import { createServer, type Server } from "node:net";
import { basename, dirname, join } from "node:path";
import { setTimeout } from "node:timers/promises";

/**
 * An OS-owned local mutex for the short session-file compare/save window.
 * There is no wire protocol or credential data. An unrelated port collision
 * only makes the operation busy; it can never admit a second owner. Closing
 * the process releases ownership without unsafe stale lock-file reclamation.
 */
export async function withPrivateFileLock<T>(path: string, action: () => T): Promise<T> {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  let canonical = join(realpathSync(dirname(path)), basename(path));
  if (process.platform === "win32") canonical = canonical.toLowerCase();
  const digest = createHash("sha256").update(canonical).digest();
  const port = 20000 + digest.readUInt16BE(0) % 40000;
  const deadline = Date.now() + 5000;
  let server: Server;
  for (;;) {
    server = createServer((socket) => socket.destroy());
    const acquired = await new Promise<boolean>((resolve, reject) => {
      server.once("error", (error: NodeJS.ErrnoException) => {
        if (error.code === "EADDRINUSE") resolve(false);
        else reject(new Error("credential_private_lock_unavailable"));
      });
      server.listen({ host: "127.0.0.1", port, exclusive: true }, () => resolve(true));
    });
    if (acquired) break;
    server.close();
    if (Date.now() >= deadline) throw new Error("credential_private_lock_busy:retry_pending_request");
    await setTimeout(20);
  }
  try {
    // Synchronous callback by contract: never hold this lock across HTTP/ACK.
    return action();
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}
