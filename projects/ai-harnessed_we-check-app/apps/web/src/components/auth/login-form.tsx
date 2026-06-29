import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { type UserRole as UserRoleType } from "@wecheck/domain";
import { toast } from "sonner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authMessages } from "@/lib/copy/checkin-messages";
import { appCopy } from "@/lib/copy/status-labels";
import { isSafeReturnUrl, resolvePostLoginRedirect } from "@/lib/auth-redirect";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

type LoginError = "InvalidCredentials" | "AccountDeactivated" | null;

interface LoginSuccessBody {
  user: {
    id: string;
    role: UserRoleType;
  };
  redirectTo?: string;
}

/** FR-02 / BR-06 / AC-02 / NFR-16 — login with returnUrl preservation and role-based redirect */
export function LoginForm() {
  const [searchParams] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<LoginError>(null);

  const sessionExpired = searchParams.get("sessionExpired") === "1";
  const returnUrl = searchParams.get("returnUrl");

  useEffect(() => {
    if (!sessionExpired) return;
    const timer = window.setTimeout(() => {
      toast.error(authMessages.sessionExpired, {
        id: "session-expired",
        duration: 5000,
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [sessionExpired]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const safeReturnUrl = isSafeReturnUrl(returnUrl) ? returnUrl : undefined;

    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          email,
          password,
          ...(safeReturnUrl ? { returnUrl: safeReturnUrl } : {}),
        }),
      });

      const data = (await res.json()) as LoginSuccessBody & {
        errorCode?: string;
        message?: string;
      };

      if (res.status === 401 && data.errorCode === "InvalidCredentials") {
        setError("InvalidCredentials");
        return;
      }

      if (res.status === 403 && data.errorCode === "AccountDeactivated") {
        setError("AccountDeactivated");
        return;
      }

      if (res.ok && data.user?.role) {
        const destination = resolvePostLoginRedirect(data.user.role, {
          returnUrl: safeReturnUrl,
          redirectTo: data.redirectTo,
        });
        window.location.href = destination;
        return;
      }

      setError("InvalidCredentials");
    } catch {
      setError("InvalidCredentials");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" data-testid="login-form">
      <div>
        <h1 className="text-h1 font-semibold">{authMessages.loginTitle}</h1>
        <p className="mt-1 text-body text-text-secondary">{appCopy.productSubtitle}</p>
      </div>

      {sessionExpired ? (
        <Alert variant="warning" data-testid="login-session-expired">
          {authMessages.sessionExpired}
        </Alert>
      ) : null}

      {error === "InvalidCredentials" ? (
        <Alert variant="danger" data-testid="login-error-InvalidCredentials">
          {authMessages.invalidCredentials}
        </Alert>
      ) : null}

      {error === "AccountDeactivated" ? (
        <Alert variant="danger" data-testid="login-error-AccountDeactivated">
          {authMessages.accountDeactivated}
        </Alert>
      ) : null}

      <div className="flex flex-col gap-2">
        <Label htmlFor="login-email">{authMessages.emailLabel}</Label>
        <Input
          id="login-email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          aria-required="true"
        />
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="login-password">{authMessages.passwordLabel}</Label>
        <Input
          id="login-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          aria-required="true"
        />
      </div>

      <Button type="submit" loading={loading} className="w-full" aria-busy={loading}>
        {authMessages.submitLabel}
      </Button>
    </form>
  );
}
