import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  createChromeDebugRelayToken,
  listChromeDebugBrowsers,
  listChromeDebugGrants,
  revokeChromeDebugBrowser,
  setChromeDebugGrant,
} from "@/features/chrome-debug/api";

export function useChromeDebug() {
  const queryClient = useQueryClient();
  const grantsQuery = useQuery({
    queryKey: ["chrome-debug", "grants"],
    queryFn: listChromeDebugGrants,
  });
  const browsersQuery = useQuery({
    queryKey: ["chrome-debug", "browsers"],
    queryFn: listChromeDebugBrowsers,
    refetchInterval: 5000,
  });
  const grantMutation = useMutation({
    mutationFn: ({ apiKeyId, enabled }: { apiKeyId: string; enabled: boolean }) =>
      setChromeDebugGrant(apiKeyId, enabled),
    onSuccess: () => {
      toast.success("Chrome Debug grant updated");
      void queryClient.invalidateQueries({ queryKey: ["chrome-debug"] });
    },
  });
  const revokeMutation = useMutation({
    mutationFn: revokeChromeDebugBrowser,
    onSuccess: () => {
      toast.success("Chrome browser revoked");
      void queryClient.invalidateQueries({ queryKey: ["chrome-debug"] });
    },
  });
  const relayMutation = useMutation({
    mutationFn: (browserId: string) => createChromeDebugRelayToken(browserId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["chrome-debug", "browsers"] });
    },
  });
  return { grantsQuery, browsersQuery, grantMutation, revokeMutation, relayMutation };
}

