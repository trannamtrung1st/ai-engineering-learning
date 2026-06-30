import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { Spinner } from "@/components/ui/spinner";
import { fetchAuthUser } from "@/lib/auth-session";
import { getRoleHome } from "@/lib/auth-redirect";

/** AC-18e / FR-18 — authenticated visitors at / redirect to role home hub */
export function RoleHomeRedirect({ children }: { children: React.ReactNode }) {
  const [redirectTo, setRedirectTo] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      const result = await fetchAuthUser();
      if (cancelled) return;

      if (result.ok) {
        setRedirectTo(getRoleHome(result.user.role));
        return;
      }

      setReady(true);
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  if (redirectTo) {
    return <Navigate to={redirectTo} replace />;
  }

  if (!ready) {
    return (
      <div className="flex min-h-[200px] items-center justify-center" aria-busy="true">
        <Spinner />
      </div>
    );
  }

  return children;
}
