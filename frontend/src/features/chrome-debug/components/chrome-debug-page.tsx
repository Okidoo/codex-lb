import { Copy, Download, ExternalLink, KeyRound, Monitor, PlugZap, Trash2 } from "lucide-react";
import { useState } from "react";
import { AlertMessage } from "@/components/alert-message";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { CHROME_DEBUG_EXTENSION_URL } from "@/features/chrome-debug/api";
import { useChromeDebug } from "@/features/chrome-debug/hooks/use-chrome-debug";
import type { ChromeDebugRelayToken } from "@/features/chrome-debug/schemas";
import { getErrorMessageOrNull } from "@/utils/errors";

function copyToClipboard(value: string) {
  return navigator.clipboard.writeText(value);
}

function RelayResult({ relay }: { relay: ChromeDebugRelayToken | null }) {
  if (!relay) return null;
  return (
    <div className="rounded-lg border bg-muted/40 p-3 text-sm">
      <div className="mb-2 font-medium">Relay created</div>
      <div className="grid gap-2">
        <code className="block overflow-x-auto rounded-md bg-background px-2 py-1 text-xs">{relay.jsonListUrl}</code>
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="outline" onClick={() => void copyToClipboard(relay.jsonListUrl)}>
            <Copy className="mr-1.5 size-3.5" />
            Copy /json/list
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={() => window.open(relay.jsonListUrl, "_blank")}>
            <ExternalLink className="mr-1.5 size-3.5" />
            Open
          </Button>
        </div>
      </div>
    </div>
  );
}

export function ChromeDebugPage() {
  const { grantsQuery, browsersQuery, grantMutation, revokeMutation, relayMutation } = useChromeDebug();
  const [relay, setRelay] = useState<ChromeDebugRelayToken | null>(null);
  const grants = grantsQuery.data?.grants ?? [];
  const browsers = browsersQuery.data?.browsers ?? [];
  const error =
    getErrorMessageOrNull(grantsQuery.error) ||
    getErrorMessageOrNull(browsersQuery.error) ||
    getErrorMessageOrNull(grantMutation.error) ||
    getErrorMessageOrNull(revokeMutation.error) ||
    getErrorMessageOrNull(relayMutation.error);

  const createRelay = async (browserId: string) => {
    const result = await relayMutation.mutateAsync(browserId);
    setRelay(result);
  };

  return (
    <div className="animate-fade-in-up space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Chrome Debug</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Bridge active Chrome tabs to Codex clients through authenticated CDP relay URLs.
        </p>
      </div>

      {error ? <AlertMessage variant="error">{error}</AlertMessage> : null}

      <section className="rounded-lg border bg-card p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Download className="size-4" />
              Chrome extension
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              Download the unpacked extension ZIP, extract it, then load it from chrome://extensions.
            </p>
          </div>
          <Button type="button" onClick={() => window.open(CHROME_DEBUG_EXTENSION_URL, "_blank")}>
            <Download className="mr-1.5 size-4" />
            Download ZIP
          </Button>
        </div>
      </section>

      <section className="rounded-lg border bg-card p-4">
        <div className="mb-4 flex items-center gap-2 text-sm font-semibold">
          <KeyRound className="size-4" />
          API key access
        </div>
        <div className="divide-y rounded-lg border">
          {grants.length === 0 ? (
            <div className="p-4 text-sm text-muted-foreground">No API keys found.</div>
          ) : (
            grants.map((grant) => (
              <div key={grant.apiKeyId} className="flex flex-wrap items-center justify-between gap-3 p-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{grant.apiKeyName}</span>
                    <Badge variant={grant.enabled ? "default" : "secondary"}>
                      {grant.enabled ? "Enabled" : "Disabled"}
                    </Badge>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {grant.keyPrefix} · {grant.onlineBrowserCount}/{grant.browserCount} online
                  </div>
                </div>
                <Switch
                  checked={grant.enabled}
                  disabled={grantMutation.isPending}
                  aria-label={`Allow Chrome Debug for ${grant.apiKeyName}`}
                  onCheckedChange={(enabled) => grantMutation.mutate({ apiKeyId: grant.apiKeyId, enabled })}
                />
              </div>
            ))
          )}
        </div>
      </section>

      <section className="rounded-lg border bg-card p-4">
        <div className="mb-4 flex items-center gap-2 text-sm font-semibold">
          <Monitor className="size-4" />
          Active browsers
        </div>
        <div className="grid gap-3">
          {browsers.length === 0 ? (
            <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
              No Chrome browsers registered yet.
            </div>
          ) : (
            browsers.map((browser) => (
              <div key={browser.id} className="rounded-lg border p-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{browser.label}</span>
                      <Badge variant={browser.status === "online" ? "default" : "secondary"}>{browser.status}</Badge>
                      {browser.apiKeyName ? <Badge variant="outline">{browser.apiKeyName}</Badge> : null}
                    </div>
                    <div className="mt-1 truncate text-xs text-muted-foreground">
                      {browser.targetCount} targets · {browser.extensionVersion ?? "extension"} · {browser.id}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={browser.status !== "online" || relayMutation.isPending}
                      onClick={() => void createRelay(browser.id)}
                    >
                      <PlugZap className="mr-1.5 size-3.5" />
                      Relay URL
                    </Button>
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      disabled={revokeMutation.isPending}
                      onClick={() => revokeMutation.mutate(browser.id)}
                    >
                      <Trash2 className="size-4" />
                      <span className="sr-only">Revoke {browser.label}</span>
                    </Button>
                  </div>
                </div>
                {browser.targets.length > 0 ? (
                  <div className="mt-3 grid gap-1">
                    {browser.targets.slice(0, 5).map((target) => (
                      <div key={target.id} className="truncate rounded-md bg-muted/50 px-2 py-1 text-xs">
                        {target.title || target.url || target.id}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ))
          )}
        </div>
      </section>

      <RelayResult relay={relay} />
    </div>
  );
}
