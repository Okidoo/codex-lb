import { get } from "@/lib/api-client";

import { CodexSetupSchema } from "@/features/codex-setup/schemas";

export function getCodexSetup() {
	return get("/codex/setup", CodexSetupSchema);
}
