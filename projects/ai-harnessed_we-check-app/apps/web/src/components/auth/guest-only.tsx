import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Spinner } from "@/components/ui/spinner";
import { fetchAuthUser } from "@/lib/auth-session";
import { resolvePostLoginRedirect } from "@/lib/auth-redirect";

/** FR-02 — redirect authenticated visitors away from /login to role home or returnUrl */
export function GuestOnly({ children }: { children: React.ReactNode }) {
  const [searchParams] = useSearchParams();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      const result = await fetchAuthUser();
      if (cancelled) return;

      if (result.ok) {
        const returnUrl = searchParams.get("returnUrl");
        window.location.href = resolvePostLoginRedirect(result.user.role, { returnUrl });
        return;
      }

      setReady(true);
    })();

    return () => {
      cancelled = true;
    };
  }, [searchParams]);

  if (!ready) {
    return (
      <div className="flex min-h-[200px] items-center justify-center" aria-busy="true">
        <Spinner />
      </div>
    );
  }

  return children;
}
