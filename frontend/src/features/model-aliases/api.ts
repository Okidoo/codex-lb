import { del, get, post } from "@/lib/api-client";
import {
	ModelAliasListSchema,
	ModelAliasSchema,
	ModelAliasUpsertRequestSchema,
	type ModelAliasUpsertRequest,
} from "@/features/model-aliases/schemas";

const MODEL_ALIASES_BASE_PATH = "/api/model-aliases";

export function listModelAliases() {
	return get(MODEL_ALIASES_BASE_PATH, ModelAliasListSchema);
}

export function upsertModelAlias(payload: ModelAliasUpsertRequest) {
	const validated = ModelAliasUpsertRequestSchema.parse(payload);
	return post(MODEL_ALIASES_BASE_PATH, ModelAliasSchema, { body: validated });
}

export function deleteModelAlias(aliasId: string) {
	return del(`${MODEL_ALIASES_BASE_PATH}/${encodeURIComponent(aliasId)}`);
}
