import { z } from "zod";

export const ChromeDebugTargetSchema = z.object({
  id: z.string(),
  type: z.string().nullable().default(null),
  title: z.string().nullable().default(null),
  url: z.string().nullable().default(null),
  attached: z.boolean().default(false),
  browserContextId: z.string().nullable().default(null),
  raw: z.record(z.string(), z.unknown()).default({}),
});

export const ChromeDebugBrowserSchema = z.object({
  id: z.string(),
  apiKeyId: z.string(),
  apiKeyName: z.string().nullable().default(null),
  label: z.string(),
  status: z.string(),
  targetCount: z.number().int().nonnegative().default(0),
  targets: z.array(ChromeDebugTargetSchema).default([]),
  instanceId: z.string().nullable().default(null),
  userAgent: z.string().nullable().default(null),
  extensionVersion: z.string().nullable().default(null),
  isRevoked: z.boolean().default(false),
  createdAt: z.iso.datetime({ offset: true }),
  updatedAt: z.iso.datetime({ offset: true }),
  lastSeenAt: z.iso.datetime({ offset: true }).nullable().default(null),
  disconnectedAt: z.iso.datetime({ offset: true }).nullable().default(null),
});

export const ChromeDebugBrowsersResponseSchema = z.object({
  browsers: z.array(ChromeDebugBrowserSchema).default([]),
});

export const ChromeDebugGrantSchema = z.object({
  apiKeyId: z.string(),
  apiKeyName: z.string(),
  keyPrefix: z.string(),
  enabled: z.boolean().default(false),
  browserCount: z.number().int().nonnegative().default(0),
  onlineBrowserCount: z.number().int().nonnegative().default(0),
});

export const ChromeDebugGrantsResponseSchema = z.object({
  grants: z.array(ChromeDebugGrantSchema).default([]),
});

export const ChromeDebugRelayTokenResponseSchema = z.object({
  token: z.string(),
  browserId: z.string(),
  expiresAt: z.iso.datetime({ offset: true }),
  relayBaseUrl: z.string(),
  jsonVersionUrl: z.string(),
  jsonListUrl: z.string(),
});

export type ChromeDebugBrowser = z.infer<typeof ChromeDebugBrowserSchema>;
export type ChromeDebugGrant = z.infer<typeof ChromeDebugGrantSchema>;
export type ChromeDebugRelayToken = z.infer<typeof ChromeDebugRelayTokenResponseSchema>;

