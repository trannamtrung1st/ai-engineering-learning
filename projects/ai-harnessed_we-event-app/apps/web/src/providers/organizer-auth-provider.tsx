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
  requestOrganizerDevToken,
  type SessionInfo,
} from "@/lib/organizer-api";

const TOKEN_STORAGE_KEY = "we-event.organizer.auth.token";
const SUB_STORAGE_KEY = "we-event.organizer.auth.sub";
const ROLE_STORAGE_KEY = "we-event.organizer.auth.role";
const ASSIGNED_STORAGE_KEY = "we-event.organizer.auth.assigned";
const DEFAULT_ADMIN_SUB = "organizer-admin-1";

export type OrganizerRole = "OrganizerAdmin" | "OrganizerStaff";

interface OrganizerAuthContextValue {
  token: string | null;
  session: SessionInfo | null;
  isAdmin: boolean;
  isStaff: boolean;
  isLoading: boolean;
  error: string | null;
  signIn: (
    sub: string,
    role: OrganizerRole,
    assignedEventIds?: string[],
  ) => Promise<void>;
  signOut: () => void;
}

const OrganizerAuthContext = createContext<OrganizerAuthContextValue | null>(null);

function parseAssignedIds(raw: string | null): string[] {
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed)
      ? parsed.filter((id): id is string => typeof id === "string")
      : [];
  } catch {
    return [];
  }
}

export function OrganizerAuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadSession = useCallback(async (authToken: string) => {
    const me = await fetchSession(authToken);
    if (me.role !== "OrganizerAdmin" && me.role !== "OrganizerStaff") {
      throw new ApiClientError(
        "Organizer sign-in is required for this area.",
        403,
        "FORBIDDEN",
      );
    }
    setSession(me);
    setToken(authToken);
    sessionStorage.setItem(TOKEN_STORAGE_KEY, authToken);
  }, []);

  const signIn = useCallback(
    async (
      sub: string,
      role: OrganizerRole,
      assignedEventIds: string[] = [],
    ) => {
      setIsLoading(true);
      setError(null);
      try {
        const trimmed = sub.trim();
        if (!trimmed) {
          throw new Error("Organizer ID is required.");
        }
        const { token: authToken } = await requestOrganizerDevToken(
          trimmed,
          role,
          assignedEventIds,
        );
        sessionStorage.setItem(SUB_STORAGE_KEY, trimmed);
        sessionStorage.setItem(ROLE_STORAGE_KEY, role);
        sessionStorage.setItem(
          ASSIGNED_STORAGE_KEY,
          JSON.stringify(assignedEventIds),
        );
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

      const storedSub = sessionStorage.getItem(SUB_STORAGE_KEY) ?? DEFAULT_ADMIN_SUB;
      const storedRole =
        (sessionStorage.getItem(ROLE_STORAGE_KEY) as OrganizerRole | null) ??
        "OrganizerAdmin";
      const assigned = parseAssignedIds(sessionStorage.getItem(ASSIGNED_STORAGE_KEY));

      try {
        await signIn(storedSub, storedRole, assigned);
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

  const value = useMemo<OrganizerAuthContextValue>(
    () => ({
      token,
      session,
      isAdmin: session?.role === "OrganizerAdmin",
      isStaff: session?.role === "OrganizerStaff",
      isLoading,
      error,
      signIn,
      signOut,
    }),
    [token, session, isLoading, error, signIn, signOut],
  );

  return (
    <OrganizerAuthContext.Provider value={value}>{children}</OrganizerAuthContext.Provider>
  );
}

export function useOrganizerAuth(): OrganizerAuthContextValue {
  const context = useContext(OrganizerAuthContext);
  if (!context) {
    throw new Error("useOrganizerAuth must be used within OrganizerAuthProvider");
  }
  return context;
}
