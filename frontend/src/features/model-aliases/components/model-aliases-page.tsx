import { ArrowRight, Pencil, Plus, RefreshCw, Route, Save, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { AlertMessage } from "@/components/alert-message";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuthStore } from "@/features/auth/hooks/use-auth";
import { useModelAliases } from "@/features/model-aliases/hooks/use-model-aliases";
import type { ModelAlias } from "@/features/model-aliases/schemas";

function getErrorMessage(error: unknown): string | null {
	if (!error) return null;
	return error instanceof Error ? error.message : "Request failed";
}

export function ModelAliasesPage() {
	const canWrite = useAuthStore((state) => state.canWrite);
	const { aliasesQuery, upsertMutation, deleteMutation } = useModelAliases();
	const [sourceModel, setSourceModel] = useState("");
	const [targetModel, setTargetModel] = useState("glm-5.2");
	const [enabled, setEnabled] = useState(true);

	const aliases = aliasesQuery.data?.aliases ?? [];
	const busy = upsertMutation.isPending || deleteMutation.isPending;
	const error = getErrorMessage(aliasesQuery.error);

	const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		if (!canWrite || busy) return;
		void upsertMutation
			.mutateAsync({
				sourceModel,
				targetModel,
				enabled,
			})
			.then(() => {
				setSourceModel("");
				setTargetModel("glm-5.2");
				setEnabled(true);
			})
			.catch(() => null);
	};

	const handleEdit = (alias: ModelAlias) => {
		setSourceModel(alias.sourceModel);
		setTargetModel(alias.targetModel);
		setEnabled(alias.enabled);
	};

	return (
		<div className="animate-fade-in-up space-y-6">
			<div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
				<div>
					<h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
						<Route className="h-5 w-5 text-primary" />
						Models
					</h1>
					<p className="mt-1 text-sm text-muted-foreground">Manage model aliases used before account routing.</p>
				</div>
				<Button
					type="button"
					variant="outline"
					size="sm"
					onClick={() => {
						void aliasesQuery.refetch();
					}}
					disabled={aliasesQuery.isFetching}
					className="w-fit gap-2"
				>
					<RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
					Refresh
				</Button>
			</div>

			{error ? <AlertMessage variant="error">{error}</AlertMessage> : null}
			{!canWrite ? (
				<div className="rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-xs font-medium text-foreground">
					You are viewing dashboard read-only guest access. Admin controls are disabled.
				</div>
			) : null}

			<section className="rounded-xl border bg-card p-4">
				<form className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto_auto]" onSubmit={handleSubmit}>
					<div className="space-y-1.5">
						<label className="text-xs font-medium text-muted-foreground" htmlFor="source-model">
							Source model
						</label>
						<Input
							id="source-model"
							value={sourceModel}
							onChange={(event) => setSourceModel(event.target.value)}
							placeholder="gpt-5.2"
							disabled={!canWrite || busy}
							className="font-mono text-sm"
						/>
					</div>
					<div className="hidden items-end pb-2 lg:flex">
						<ArrowRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
					</div>
					<div className="space-y-1.5">
						<label className="text-xs font-medium text-muted-foreground" htmlFor="target-model">
							Target model
						</label>
						<Input
							id="target-model"
							value={targetModel}
							onChange={(event) => setTargetModel(event.target.value)}
							placeholder="glm-5.2"
							disabled={!canWrite || busy}
							className="font-mono text-sm"
						/>
					</div>
					<label className="flex items-end gap-2 pb-2 text-xs font-medium text-muted-foreground">
						<Switch checked={enabled} onCheckedChange={setEnabled} disabled={!canWrite || busy} size="sm" />
						Enabled
					</label>
					<div className="flex items-end">
						<Button type="submit" disabled={!canWrite || busy} className="w-full gap-2 lg:w-auto">
							{sourceModel ? <Save className="h-3.5 w-3.5" aria-hidden="true" /> : <Plus className="h-3.5 w-3.5" aria-hidden="true" />}
							Save
						</Button>
					</div>
				</form>
			</section>

			<section className="rounded-xl border bg-card p-4">
				{aliasesQuery.isPending && !aliasesQuery.data ? (
					<div className="space-y-3">
						<Skeleton className="h-8 w-full" />
						<Skeleton className="h-8 w-full" />
						<Skeleton className="h-8 w-full" />
					</div>
				) : aliases.length === 0 ? (
					<p className="py-8 text-center text-sm text-muted-foreground">No model aliases configured.</p>
				) : (
					<Table>
						<TableHeader>
							<TableRow>
								<TableHead>Source</TableHead>
								<TableHead>Target</TableHead>
								<TableHead>Status</TableHead>
								<TableHead className="w-28 text-right">Actions</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{aliases.map((alias) => (
								<TableRow key={alias.id}>
									<TableCell className="font-mono text-xs">{alias.sourceModel}</TableCell>
									<TableCell className="font-mono text-xs">{alias.targetModel}</TableCell>
									<TableCell>
										<Switch
											checked={alias.enabled}
											onCheckedChange={(checked) => {
												if (!canWrite || busy) return;
												void upsertMutation
													.mutateAsync({
														sourceModel: alias.sourceModel,
														targetModel: alias.targetModel,
														enabled: checked,
													})
													.catch(() => null);
											}}
											disabled={!canWrite || busy}
											size="sm"
										/>
									</TableCell>
									<TableCell>
										<div className="flex justify-end gap-1">
											<Button
												type="button"
												variant="ghost"
												size="icon"
												aria-label={`Edit ${alias.sourceModel}`}
												onClick={() => handleEdit(alias)}
												disabled={busy}
											>
												<Pencil className="h-3.5 w-3.5" aria-hidden="true" />
											</Button>
											<Button
												type="button"
												variant="ghost"
												size="icon"
												aria-label={`Delete ${alias.sourceModel}`}
												onClick={() => {
													if (!canWrite || busy) return;
													void deleteMutation.mutateAsync(alias.id).catch(() => null);
												}}
												disabled={!canWrite || busy}
											>
												<Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
											</Button>
										</div>
									</TableCell>
								</TableRow>
							))}
						</TableBody>
					</Table>
				)}
			</section>
		</div>
	);
}
