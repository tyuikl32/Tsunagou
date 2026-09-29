import { mkdir, copyFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = resolve(packageRoot, "..", "..", "protocol", "registry", "commands.json");
const destination = resolve(packageRoot, "protocol", "registry", "commands.json");

await mkdir(dirname(destination), { recursive: true });
await copyFile(source, destination);

for (const name of ["task.begin", "task.submit", "task.create", "task.update_plan", "workspace.select", "contract.propose", "coordination.plan",
  "message.send", "message.respond", "inbox.claim", "inbox.fetch", "inbox.presented", "inbox.ack"]) {
  const relative = `schemas/commands/${name.replaceAll(".", "/")}.schema.json`;
  const target = resolve(packageRoot, "protocol", relative);
  await mkdir(dirname(target), { recursive: true });
  await copyFile(resolve(packageRoot, "..", "..", "protocol", relative), target);
}
