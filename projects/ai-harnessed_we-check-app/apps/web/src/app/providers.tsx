import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { AuthBootProvider } from "@/components/auth/auth-boot-context";
import type { AuthUser } from "@/lib/auth-session";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: true,
      retry: 1,
    },
  },
});

export function AppProviders({
  children,
  bootAuthUser = null,
}: {
  children: ReactNode;
  bootAuthUser?: AuthUser | null;
}) {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthBootProvider user={bootAuthUser}>{children}</AuthBootProvider>
    </QueryClientProvider>
  );
}
