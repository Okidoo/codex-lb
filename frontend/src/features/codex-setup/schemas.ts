import { z } from "zod";

export const CodexSetupSchema = z
	.object({
		provider: z.string(),
		base_url: z.string(),
		catalog_path: z.string(),
		models_cache_path: z.string(),
		model_count: z.number(),
		install_command: z.string(),
		uninstall_command: z.string(),
		env_key: z.string(),
	})
	.transform((value) => ({
		provider: value.provider,
		baseUrl: value.base_url,
		catalogPath: value.catalog_path,
		modelsCachePath: value.models_cache_path,
		modelCount: value.model_count,
		installCommand: value.install_command,
		uninstallCommand: value.uninstall_command,
		envKey: value.env_key,
	}));

export type CodexSetup = z.infer<typeof CodexSetupSchema>;
