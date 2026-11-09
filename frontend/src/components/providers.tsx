"use client";

import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { restoreSession } from "@/lib/api";
import { useSessionStore } from "@/store/session";

function SessionBootstrap() {
  const queryClient = useQueryClient();
  useEffect(() => {
    const unsubscribe = useSessionStore.subscribe((session, previous) => {
      const rejectedAnonymousRestore = !session.accessToken &&
        session.sessionGeneration !== previous.sessionGeneration;
      if (session.userDataEpoch !== previous.userDataEpoch || rejectedAnonymousRestore) {
        // The browser query cache contains authenticated data. Removing it also
        // detaches in-flight queries from the previous owner.
        queryClient.removeQueries();
      }
    });
    // The refresh session lives in an HttpOnly cookie, so client code cannot
    // reliably detect it before attempting restoration.
    void restoreSession();
    return unsubscribe;
  }, [queryClient]);

  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: 1
          },
          mutations: {
            retry: 0
          }
        }
      })
  );
  return (
    <QueryClientProvider client={queryClient}>
      <SessionBootstrap />
      {children}
    </QueryClientProvider>
  );
}
