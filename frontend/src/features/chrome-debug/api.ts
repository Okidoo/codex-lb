import { del, get, post, put } from "@/lib/api-client";
import { z } from "zod";
import {
  ChromeDebugBrowsersResponseSchema,
  ChromeDebugGrantsResponseSchema,
  ChromeDebugRelayTokenResponseSchema,
} from "@/features/chrome-debug/schemas";

const CHROME_DEBUG_PATH = "/api/chrome-debug";

export function listChromeDebugGrants() {
  return get(`${CHROME_DEBUG_PATH}/grants`, ChromeDebugGrantsResponseSchema);
}

export function setChromeDebugGrant(apiKeyId: string, enabled: boolean) {
  return put(`${CHROME_DEBUG_PATH}/grants/${encodeURIComponent(apiKeyId)}`, z.void(), {
    body: { enabled },
  });
}

export function listChromeDebugBrowsers() {
  return get(`${CHROME_DEBUG_PATH}/browsers`, ChromeDebugBrowsersResponseSchema);
}

export function revokeChromeDebugBrowser(browserId: string) {
  return del(`${CHROME_DEBUG_PATH}/browsers/${encodeURIComponent(browserId)}`);
}

export function createChromeDebugRelayToken(browserId: string, ttlSeconds = 300) {
  return post(
    `${CHROME_DEBUG_PATH}/browsers/${encodeURIComponent(browserId)}/relay-token`,
    ChromeDebugRelayTokenResponseSchema,
    { body: { ttlSeconds } },
  );
}

export const CHROME_DEBUG_EXTENSION_URL = `${CHROME_DEBUG_PATH}/extension.zip`;
