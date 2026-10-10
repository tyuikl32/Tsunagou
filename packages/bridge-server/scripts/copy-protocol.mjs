import { cp, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// The bridge serves each schema file verbatim as the MCP tool's `inputSchema`
// (`commandSchema()` looks in this package first), so the packaged copy has to carry *every*
// command schema, not a hand-picked list: a curated subset silently turns the rest of the
// tool surface into `command_schema_unavailable` once the bridge is installed away from its
// source checkout. Kept identical to what `tools/codegen/generate_protocol.py` writes.
const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = resolve(packageRoot, "..", "..", "protocol");

for (const directory of ["registry", "schemas"]) {
  const destination = resolve(packageRoot, "protocol", directory);
  await mkdir(dirname(destination), { recursive: true });
  await cp(resolve(source, directory), destination, { recursive: true, force: true });
}
