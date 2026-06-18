import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { describe, expect, it } from "vitest";

const execFileAsync = promisify(execFile);
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const fixtureScriptPath = path.join(repoRoot, "scripts/e2e/lib/fixture.mjs");

describe("scripts/e2e/lib/fixtures/workspace", () => {
  it("writes token auth for agents-delete-config fixture", async () => {
    const tempRoot = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-fixture-workspace-"));
    const stateDir = path.join(tempRoot, ".openclaw");
    const sharedWorkspace = path.join(tempRoot, "workspace-shared");
    try {
      await execFileAsync(process.execPath, [fixtureScriptPath, "agents-delete-config"], {
        env: {
          ...process.env,
          OPENCLAW_STATE_DIR: stateDir,
          SHARED_WORKSPACE: sharedWorkspace,
        },
      });

      const config = JSON.parse(await fs.readFile(path.join(stateDir, "openclaw.json"), "utf8"));
      expect(config.gateway?.auth).toEqual({
        mode: "token",
        token: "openclaw-e2e-agents-delete-shared-workspace-token",
      });
      expect(config.agents?.list).toEqual([
        { id: "main", workspace: sharedWorkspace },
        { id: "ops", workspace: sharedWorkspace },
      ]);
    } finally {
      await fs.rm(tempRoot, { recursive: true, force: true });
    }
  });
});
