import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authMessages } from "@/lib/copy/checkin-messages";
import { appCopy } from "@/lib/copy/status-labels";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

type LoginError = "InvalidCredentials" | "AccountDeactivated" | null;

/** NFR-17 / FR-02 — login form with Vietnamese labels and error states */
export function LoginForm() {
  const [searchParams] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<LoginError>(null);

  const sessionExpired = searchParams.get("sessionExpired") === "1";

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

    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password }),
      });

      const data = (await res.json()) as { errorCode?: string; message?: string };

      if (res.status === 401 && data.errorCode === "InvalidCredentials") {
        setError("InvalidCredentials");
        return;
      }

      if (res.status === 403 && data.errorCode === "AccountDeactivated") {
        setError("AccountDeactivated");
        return;
      }

      if (res.ok) {
        const returnUrl = searchParams.get("returnUrl") ?? "/";
        window.location.href = returnUrl;
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
        />
      </div>

      <Button type="submit" loading={loading} className="w-full">
        {authMessages.submitLabel}
      </Button>
    </form>
  );
}
