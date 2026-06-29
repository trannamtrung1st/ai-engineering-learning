import { useEffect, useState } from "react";
import { Outlet, useLocation, useOutletContext } from "react-router-dom";
import { Spinner } from "@/components/ui/spinner";
import type { AuthUser } from "@/lib/auth-session";
import { fetchAuthUser } from "@/lib/auth-session";
import {
  currentPathWithSearch,
  loginReturnUrl,
} from "@/lib/auth-redirect";

export interface AuthOutletContext {
  user: AuthUser;
}

/** BR-06 / FR-02 — gate protected routes; preserve returnUrl on auth failure */
export function RequireAuth() {
  const location = useLocation();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [networkError, setNetworkError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      const result = await fetchAuthUser();
      if (cancelled) return;

      if (result.ok) {
        setUser(result.user);
        return;
      }

      if (result.errorCode === "NetworkError") {
        setNetworkError(true);
        return;
      }

      const returnPath = currentPathWithSearch(location);
      window.location.href = loginReturnUrl(returnPath, {
        sessionExpired: result.errorCode === "SessionExpired",
      });
    })();

    return () => {
      cancelled = true;
    };
  }, [location]);

  if (networkError) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <p className="text-body text-text-secondary">
          Không thể kết nối máy chủ. Vui lòng thử lại.
        </p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center" aria-busy="true">
        <Spinner />
      </div>
    );
  }

  return <Outlet context={{ user } satisfies AuthOutletContext} />;
}

export function useAuthUser(): AuthUser {
  return useOutletContext<AuthOutletContext>().user;
}
