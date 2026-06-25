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

import { ApiClientError } from "@/lib/api-client";
import {
  fetchSession,
  requestDevToken,
  type SessionInfo,
} from "@/lib/participant-api";

const TOKEN_STORAGE_KEY = "we-event.auth.token";
const SUB_STORAGE_KEY = "we-event.auth.sub";
const DEFAULT_PARTICIPANT_SUB = "participant-1";

interface AuthContextValue {
  token: string | null;
  session: SessionInfo | null;
  participantId: string | null;
  isLoading: boolean;
  error: string | null;
  signIn: (sub: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadSession = useCallback(async (authToken: string) => {
    const me = await fetchSession(authToken);
    if (me.role !== "Participant") {
      throw new ApiClientError(
        "Participant sign-in is required for this area.",
        403,
        "FORBIDDEN",
      );
    }
    setSession(me);
    setToken(authToken);
    sessionStorage.setItem(TOKEN_STORAGE_KEY, authToken);
  }, []);

  const signIn = useCallback(
    async (sub: string) => {
      setIsLoading(true);
      setError(null);
      try {
        const trimmed = sub.trim();
        if (!trimmed) {
          throw new Error("Participant ID is required.");
        }
        const { token: authToken } = await requestDevToken(trimmed);
        sessionStorage.setItem(SUB_STORAGE_KEY, trimmed);
        await loadSession(authToken);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Sign-in failed. Try again.";
        setError(message);
        setSession(null);
        setToken(null);
        sessionStorage.removeItem(TOKEN_STORAGE_KEY);
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
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      const storedToken = sessionStorage.getItem(TOKEN_STORAGE_KEY);
      if (storedToken) {
        try {
          await loadSession(storedToken);
          if (!cancelled) {
            setIsLoading(false);
          }
          return;
        } catch {
          sessionStorage.removeItem(TOKEN_STORAGE_KEY);
        }
      }

      const storedSub =
        sessionStorage.getItem(SUB_STORAGE_KEY) ?? DEFAULT_PARTICIPANT_SUB;
      try {
        await signIn(storedSub);
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
  }, [loadSession, signIn]);

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      session,
      participantId: session?.actorId ?? null,
      isLoading,
      error,
      signIn,
      signOut,
    }),
    [token, session, isLoading, error, signIn, signOut],
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
