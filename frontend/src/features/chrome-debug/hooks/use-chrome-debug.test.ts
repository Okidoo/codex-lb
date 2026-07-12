// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type PropsWithChildren } from "react";
import { describe, expect, it, vi } from "vitest";

import { useChromeDebug } from "@/features/chrome-debug/hooks/use-chrome-debug";

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

describe("useChromeDebug", () => {
  it("loads grants and browsers, then invalidates after mutations", async () => {
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useChromeDebug(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.grantsQuery.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.browsersQuery.isSuccess).toBe(true));
    expect(result.current.grantsQuery.data?.grants[0]?.apiKeyId).toBe("key_1");
    expect(result.current.browsersQuery.data?.browsers[0]?.id).toBe("browser_primary");

    await result.current.grantMutation.mutateAsync({ apiKeyId: "key_2", enabled: true });
    await result.current.relayMutation.mutateAsync("browser_primary");
    await result.current.revokeMutation.mutateAsync("browser_primary");

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["chrome-debug"] });
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["chrome-debug", "browsers"] });
  });
});
