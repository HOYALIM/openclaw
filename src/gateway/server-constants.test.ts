import { afterEach, describe, expect, it } from "vitest";
import {
  DEFAULT_HANDSHAKE_TIMEOUT_MS,
  LOOPBACK_HANDSHAKE_TIMEOUT_MS,
  getHandshakeTimeoutMs,
} from "./server-constants.js";

const originalTestHandshakeTimeout = process.env.OPENCLAW_TEST_HANDSHAKE_TIMEOUT_MS;

afterEach(() => {
  if (originalTestHandshakeTimeout === undefined) {
    delete process.env.OPENCLAW_TEST_HANDSHAKE_TIMEOUT_MS;
  } else {
    process.env.OPENCLAW_TEST_HANDSHAKE_TIMEOUT_MS = originalTestHandshakeTimeout;
  }
});

describe("getHandshakeTimeoutMs", () => {
  it("uses a longer timeout for loopback remotes", () => {
    expect(getHandshakeTimeoutMs("127.0.0.1")).toBe(LOOPBACK_HANDSHAKE_TIMEOUT_MS);
    expect(getHandshakeTimeoutMs("::1")).toBe(LOOPBACK_HANDSHAKE_TIMEOUT_MS);
  });

  it("keeps the default timeout for non-loopback remotes", () => {
    expect(getHandshakeTimeoutMs("192.168.1.20")).toBe(DEFAULT_HANDSHAKE_TIMEOUT_MS);
    expect(getHandshakeTimeoutMs()).toBe(DEFAULT_HANDSHAKE_TIMEOUT_MS);
  });

  it("preserves test overrides ahead of loopback defaults", () => {
    process.env.OPENCLAW_TEST_HANDSHAKE_TIMEOUT_MS = "250";

    expect(getHandshakeTimeoutMs("127.0.0.1")).toBe(250);
    expect(getHandshakeTimeoutMs("192.168.1.20")).toBe(250);
  });
});
