import { createHash } from "node:crypto";
import { mkdirSync, realpathSync } from "node:fs";
import { createServer, type Server } from "node:net";
import { basename, dirname, join } from "node:path";
import { setTimeout } from "node:timers/promises";

const LOCK_PORT_START = 20000;
const LOCK_PORT_COUNT = 40000;

/**
 * An OS-owned local mutex for the short session-file compare/save window.
 * Windows named pipes and Linux abstract sockets use the complete path hash,
 * so unrelated TCP listeners cannot block a credential write. The kernel
 * releases the name on process exit; no stale PID/file reclamation is needed.
 * Other platforms retain the fail-busy TCP fallback.
 */
export async function withPrivateFileLock<T>(path: string, action: () => T): Promise<T> {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  let canonical = join(realpathSync(dirname(path)), basename(path));
  if (process.platform === "win32") canonical = canonical.toLowerCase();
  const digest = createHash("sha256").update(canonical).digest();
  const name = "tsunagou-private-lock-" + digest.toString("hex");
  const address = process.platform === "win32" ? { path: "\\\\.\\pipe\\" + name }
    : process.platform === "linux" ? { path: "\0" + name }
    : { host: "127.0.0.1", port: LOCK_PORT_START + digest.readUInt16BE(0) % LOCK_PORT_COUNT };
  const deadline = Date.now() + 5000;
  let server: Server;
  for (;;) {
    server = createServer((socket) => socket.destroy());
    const acquired = await new Promise<"acquired" | "busy">((resolve, reject) => {
      server.once("error", (error: NodeJS.ErrnoException) => {
        if (error.code === "EADDRINUSE" || (process.platform === "win32" && error.code === "EBUSY")) resolve("busy");
        else reject(new Error("credential_private_lock_unavailable"));
      });
      server.listen({ ...address, exclusive: true }, () => resolve("acquired"));
    });
    if (acquired === "acquired") break;
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
