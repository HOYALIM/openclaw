import { describe, expect, it } from "vitest";
import { resolveRepoRoot } from "../../scripts/lib/ts-guard-utils.mjs";

describe("ts-guard-utils", () => {
  it("resolves the repository root from files in scripts/", () => {
    expect(
      resolveRepoRoot(
        "file:///Users/holim/code/openclaw/openclaw/scripts/check-no-raw-channel-fetch.mjs",
      ),
    ).toBe("/Users/holim/code/openclaw/openclaw");
  });
});
