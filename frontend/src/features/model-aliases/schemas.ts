import { z } from "zod";

export const ModelAliasSchema = z.object({
	id: z.string(),
	sourceModel: z.string(),
	targetModel: z.string(),
	enabled: z.boolean(),
	createdAt: z.iso.datetime({ offset: true }),
	updatedAt: z.iso.datetime({ offset: true }),
});

export const ModelAliasListSchema = z.object({
	aliases: z.array(ModelAliasSchema).default([]),
});

export const ModelAliasUpsertRequestSchema = z.object({
	sourceModel: z.string().trim().min(1).max(128),
	targetModel: z.string().trim().min(1).max(128),
	enabled: z.boolean().default(true),
});

export type ModelAlias = z.infer<typeof ModelAliasSchema>;
export type ModelAliasList = z.infer<typeof ModelAliasListSchema>;
export type ModelAliasUpsertRequest = z.infer<typeof ModelAliasUpsertRequestSchema>;
