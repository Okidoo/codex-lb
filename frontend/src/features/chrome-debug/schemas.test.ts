import { describe, expect, it } from "vitest";

import {
  ChromeDebugBrowsersResponseSchema,
  ChromeDebugGrantsResponseSchema,
  ChromeDebugRelayTokenResponseSchema,
} from "@/features/chrome-debug/schemas";

const ISO = "2026-07-10T12:00:00Z";

describe("Chrome Debug schemas", () => {
  it("parses browser responses with targets and nullable metadata", () => {
    const parsed = ChromeDebugBrowsersResponseSchema.parse({
      browsers: [
        {
          id: "browser-1",
          apiKeyId: "key-1",
          apiKeyName: null,
          label: "Work Chrome",
          status: "online",
          targetCount: 1,
          targets: [
            {
              id: "target-1",
              type: "page",
              title: "Codex LB",
              url: "https://codex.okidoo.co/dashboard",
              attached: false,
              browserContextId: null,
              raw: { tabId: 123 },
            },
          ],
          instanceId: "local",
          userAgent: "Chrome/118",
          extensionVersion: "0.1.0",
          isRevoked: false,
          createdAt: ISO,
          updatedAt: ISO,
          lastSeenAt: ISO,
          disconnectedAt: null,
        },
      ],
    });

    expect(parsed.browsers[0]?.targets[0]?.raw.tabId).toBe(123);
    expect(parsed.browsers[0]?.disconnectedAt).toBeNull();
  });

  it("defaults missing list fields", () => {
    expect(ChromeDebugBrowsersResponseSchema.parse({}).browsers).toEqual([]);
    expect(ChromeDebugGrantsResponseSchema.parse({}).grants).toEqual([]);
  });

  it("parses grants and relay token payloads", () => {
    const grants = ChromeDebugGrantsResponseSchema.parse({
      grants: [
        {
          apiKeyId: "key-1",
          apiKeyName: "Dev key",
          keyPrefix: "sk-clb",
          enabled: true,
          browserCount: 2,
          onlineBrowserCount: 1,
        },
      ],
    });
    const relay = ChromeDebugRelayTokenResponseSchema.parse({
      token: "clb_chr_relay_test",
      browserId: "browser-1",
      expiresAt: ISO,
      relayBaseUrl: "http://localhost/chrome-debug/relay/clb_chr_relay_test",
      jsonVersionUrl: "http://localhost/chrome-debug/relay/clb_chr_relay_test/json/version",
      jsonListUrl: "http://localhost/chrome-debug/relay/clb_chr_relay_test/json/list",
    });

    expect(grants.grants[0]?.enabled).toBe(true);
    expect(relay.browserId).toBe("browser-1");
  });
});
