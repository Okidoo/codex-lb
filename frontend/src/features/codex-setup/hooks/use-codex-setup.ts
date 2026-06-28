import { useQuery } from "@tanstack/react-query";

import { getCodexSetup } from "@/features/codex-setup/api";

export function useCodexSetup() {
	const setupQuery = useQuery({
		queryKey: ["codex-setup"],
		queryFn: getCodexSetup,
		staleTime: 5 * 60 * 1000,
	});

	return { setupQuery };
}
