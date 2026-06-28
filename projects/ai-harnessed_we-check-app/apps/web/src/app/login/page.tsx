import { LoginForm } from "@/components/auth/login-form";
import { GuestOnly } from "@/components/auth/guest-only";

/** FR-02 / AC-02 — login page with returnUrl deep-link and role-based redirect */
export function LoginPage() {
  return (
    <GuestOnly>
      <LoginForm />
    </GuestOnly>
  );
}
