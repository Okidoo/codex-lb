import { useState } from "react";
import type { FormEvent } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ZaiAccountCreateRequest } from "@/features/accounts/schemas";

export type ZaiAccountDialogProps = {
  open: boolean;
  busy: boolean;
  error: string | null;
  onOpenChange: (open: boolean) => void;
  onCreate: (payload: ZaiAccountCreateRequest) => Promise<void>;
};

export function ZaiAccountDialog({
  open,
  busy,
  error,
  onOpenChange,
  onCreate,
}: ZaiAccountDialogProps) {
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");

  const reset = () => {
    setLabel("");
    setApiKey("");
  };

  const handleOpenChange = (nextOpen: boolean) => {
    onOpenChange(nextOpen);
    if (!nextOpen) {
      reset();
    }
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedApiKey = apiKey.trim();
    if (!trimmedApiKey) {
      return;
    }
    const trimmedLabel = label.trim();
    await onCreate({
      apiKey: trimmedApiKey,
      ...(trimmedLabel ? { label: trimmedLabel } : {}),
    });
    handleOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add Z.AI account</DialogTitle>
          <DialogDescription>Store a coding-plan API key for GLM routing.</DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="zai-account-label">Label</Label>
            <Input
              id="zai-account-label"
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              placeholder="Z.AI"
              autoComplete="off"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="zai-api-key">API key</Label>
            <Input
              id="zai-api-key"
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              autoComplete="off"
              required
            />
          </div>

          {error ? (
            <p className="rounded-md border border-destructive/30 bg-destructive/10 px-2 py-1 text-xs text-destructive">
              {error}
            </p>
          ) : null}

          <DialogFooter>
            <Button type="submit" disabled={busy || !apiKey.trim()}>
              Add account
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

