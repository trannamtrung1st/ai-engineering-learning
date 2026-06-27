"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  fetchSession,
  loginWithCredentials,
  registerAccount,
  type AuthCredentials,
  type RegisterInput,
  type SessionInfo,
} from "@/lib/session-api";

export const TOKEN_STORAGE_KEY = "we-event.auth.token";
const LEGACY_ORGANIZER_TOKEN_KEY = "we-event.organizer.auth.token";

interface AuthContextValue {
  token: string | null;
  session: SessionInfo | null;
  participantId: string | null;
  isAdmin: boolean;
  isStaff: boolean;
  isLoading: boolean;
  error: string | null;
  signIn: (credentials: AuthCredentials) => Promise<SessionInfo>;
  register: (input: RegisterInput) => Promise<SessionInfo>;
  signOut: () => void;
  clearError: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function clearStoredAuth(): void {
  sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  sessionStorage.removeItem(LEGACY_ORGANIZER_TOKEN_KEY);
  sessionStorage.removeItem("we-event.auth.sub");
  sessionStorage.removeItem("we-event.organizer.auth.sub");
  sessionStorage.removeItem("we-event.organizer.auth.role");
  sessionStorage.removeItem("we-event.organizer.auth.assigned");
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadSession = useCallback(async (authToken: string): Promise<SessionInfo> => {
    const me = await fetchSession(authToken);
    setSession(me);
    setToken(authToken);
    sessionStorage.setItem(TOKEN_STORAGE_KEY, authToken);
    return me;
  }, []);

  const establishSession = useCallback(
    async (authToken: string) => {
      setIsLoading(true);
      setError(null);
      try {
        await loadSession(authToken);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Session could not be restored.";
        setError(message);
        setSession(null);
        setToken(null);
        clearStoredAuth();
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [loadSession],
  );

  const signIn = useCallback(
    async (credentials: AuthCredentials) => {
      setIsLoading(true);
      setError(null);
      try {
        const { token: authToken } = await loginWithCredentials(credentials);
        return await loadSession(authToken);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Sign-in failed. Try again.";
        setError(message);
        setSession(null);
        setToken(null);
        clearStoredAuth();
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [loadSession],
  );

  const register = useCallback(
    async (input: RegisterInput) => {
      setIsLoading(true);
      setError(null);
      try {
        const { token: authToken } = await registerAccount(input);
        return await loadSession(authToken);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Sign-up failed. Try again.";
        setError(message);
        setSession(null);
        setToken(null);
        clearStoredAuth();
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [loadSession],
  );

  const signOut = useCallback(() => {
    setToken(null);
    setSession(null);
    setError(null);
    clearStoredAuth();
  }, []);

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      const storedToken =
        sessionStorage.getItem(TOKEN_STORAGE_KEY) ??
        sessionStorage.getItem(LEGACY_ORGANIZER_TOKEN_KEY);
      if (!storedToken) {
        if (!cancelled) {
          setIsLoading(false);
        }
        return;
      }

      try {
        await establishSession(storedToken);
      } catch {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [establishSession]);

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      session,
      participantId: session?.actorId ?? null,
      isAdmin: session?.role === "OrganizerAdmin",
      isStaff: session?.role === "OrganizerStaff",
      isLoading,
      error,
      signIn,
      register,
      signOut,
      clearError,
    }),
    [token, session, isLoading, error, signIn, register, signOut, clearError],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
