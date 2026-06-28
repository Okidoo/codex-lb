import { Clipboard, RefreshCw, Route } from "lucide-react";
import { toast } from "sonner";

import { AlertMessage } from "@/components/alert-message";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useCodexSetup } from "@/features/codex-setup/hooks/use-codex-setup";

function getErrorMessage(error: unknown): string | null {
	if (!error) return null;
	return error instanceof Error ? error.message : "Request failed";
}

export function CodexSetupPage() {
	const { setupQuery } = useCodexSetup();
	const setup = setupQuery.data;
	const setupError = getErrorMessage(setupQuery.error);

	const copy = (value: string, label: string) => {
		if (!navigator.clipboard) {
			toast.error("Clipboard unavailable");
			return;
		}
		void navigator.clipboard
			.writeText(value)
			.then(() => toast.success(`${label} copied`))
			.catch(() => toast.error("Copy failed"));
	};

	return (
		<div className="animate-fade-in-up space-y-6">
			<div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
				<div>
					<h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
						<Route className="h-5 w-5 text-primary" />
						Models
					</h1>
					<p className="mt-1 text-sm text-muted-foreground">Codex App catalog and provider setup.</p>
				</div>
				<Button
					type="button"
					variant="outline"
					size="sm"
					onClick={() => {
						void setupQuery.refetch();
					}}
					disabled={setupQuery.isFetching}
					className="w-fit gap-2"
				>
					<RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
					Refresh
				</Button>
			</div>

			{setupError ? <AlertMessage variant="error">{setupError}</AlertMessage> : null}

			<section className="rounded-xl border bg-card p-4">
				<div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
					<div>
						<h2 className="text-sm font-semibold">Codex App Setup</h2>
						<p className="text-xs text-muted-foreground">Local catalog plus provider config for Codex App and CLI.</p>
					</div>
					<div className="flex flex-wrap gap-2">
						<Badge variant="outline">{setup?.provider ?? "codex-lb"}</Badge>
						<Badge variant="secondary">{setup ? `${setup.modelCount} models` : "catalog"}</Badge>
					</div>
				</div>

				{setupQuery.isPending && !setup ? (
					<div className="space-y-3">
						<Skeleton className="h-9 w-full" />
						<Skeleton className="h-9 w-full" />
					</div>
				) : setup ? (
					<div className="grid gap-3 lg:grid-cols-2">
						<CommandField label="Install" value={setup.installCommand} onCopy={() => copy(setup.installCommand, "Install command")} />
						<CommandField
							label="Uninstall"
							value={setup.uninstallCommand}
							onCopy={() => copy(setup.uninstallCommand, "Uninstall command")}
						/>
						<ReadonlyField label="Catalog" value={setup.catalogPath} />
						<ReadonlyField label="API key env" value={setup.envKey} />
					</div>
				) : null}
			</section>
		</div>
	);
}

function CommandField({ label, value, onCopy }: { label: string; value: string; onCopy: () => void }) {
	return (
		<div className="space-y-1.5">
			<label className="text-xs font-medium text-muted-foreground">{label}</label>
			<div className="flex gap-2">
				<Input readOnly value={value} className="font-mono text-xs" />
				<Button type="button" variant="outline" size="icon" aria-label={`Copy ${label}`} onClick={onCopy}>
					<Clipboard className="h-3.5 w-3.5" aria-hidden="true" />
				</Button>
			</div>
		</div>
	);
}

function ReadonlyField({ label, value }: { label: string; value: string }) {
	return (
		<div className="space-y-1.5">
			<label className="text-xs font-medium text-muted-foreground">{label}</label>
			<Input readOnly value={value} className="font-mono text-xs" />
		</div>
	);
}
