import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { deleteModelAlias, listModelAliases, upsertModelAlias } from "@/features/model-aliases/api";
import type { ModelAliasUpsertRequest } from "@/features/model-aliases/schemas";

const MODEL_ALIASES_QUERY_KEY = ["model-aliases", "list"] as const;

export function useModelAliases() {
	const queryClient = useQueryClient();
	const aliasesQuery = useQuery({
		queryKey: MODEL_ALIASES_QUERY_KEY,
		queryFn: listModelAliases,
	});

	const upsertMutation = useMutation({
		mutationFn: (payload: ModelAliasUpsertRequest) => upsertModelAlias(payload),
		onSuccess: () => {
			toast.success("Model alias saved");
			void queryClient.invalidateQueries({ queryKey: MODEL_ALIASES_QUERY_KEY });
		},
		onError: (error: Error) => {
			toast.error(error.message || "Model alias save failed");
		},
	});

	const deleteMutation = useMutation({
		mutationFn: deleteModelAlias,
		onSuccess: () => {
			toast.success("Model alias deleted");
			void queryClient.invalidateQueries({ queryKey: MODEL_ALIASES_QUERY_KEY });
		},
		onError: (error: Error) => {
			toast.error(error.message || "Model alias delete failed");
		},
	});

	return { aliasesQuery, upsertMutation, deleteMutation };
}
