import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { Spinner } from "@/components/ui/spinner";
import { fetchSetupStatus } from "@/lib/setup-api";

/** FR-17 / AC-17 — gate routes until first admin bootstrap completes */
export function SetupGuard() {
  const location = useLocation();
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null);
  const [networkError, setNetworkError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      const result = await fetchSetupStatus();
      if (cancelled) return;

      if (!result.ok) {
        setNetworkError(true);
        return;
      }

      setNeedsSetup(result.data.needsSetup);
    })();

    return () => {
      cancelled = true;
    };
  }, [location.pathname]);

  if (networkError) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <p className="text-body text-text-secondary">
          Không thể kết nối máy chủ. Vui lòng thử lại.
        </p>
      </div>
    );
  }

  if (needsSetup === null) {
    return (
      <div className="flex min-h-screen items-center justify-center" aria-busy="true">
        <Spinner />
      </div>
    );
  }

  const isSetupRoute =
    location.pathname === "/setup" || location.pathname.startsWith("/setup/");

  if (needsSetup) {
    if (!isSetupRoute) {
      return <Navigate to="/setup" replace state={{ from: location }} />;
    }
    return <Outlet />;
  }

  if (isSetupRoute) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
