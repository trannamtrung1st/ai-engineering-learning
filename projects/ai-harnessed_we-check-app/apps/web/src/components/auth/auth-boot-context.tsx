import { createContext, useContext, type ReactNode } from "react";
import type { AuthUser } from "@/lib/auth-session";

const AuthBootContext = createContext<AuthUser | null>(null);

export function AuthBootProvider({
  user,
  children,
}: {
  user: AuthUser | null;
  children: ReactNode;
}) {
  return <AuthBootContext.Provider value={user}>{children}</AuthBootContext.Provider>;
}

export function useAuthBootUser(): AuthUser | null {
  return useContext(AuthBootContext);
}
