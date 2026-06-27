"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { z } from "zod";

import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { resolvePostAuthRedirect } from "@/lib/auth-redirect";
import { useAuth } from "@/providers/auth-provider";

const loginSchema = z.object({
  email: z.string().email("Enter a valid email address."),
  password: z.string().min(1, "Password is required."),
});

export function LoginPageClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const returnUrl = searchParams.get("returnUrl");
  const { token, session, isLoading, error, signIn, clearError } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!isLoading && token && session) {
      router.replace(resolvePostAuthRedirect(returnUrl, session.role));
    }
  }, [isLoading, token, session, returnUrl, router]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    clearError();
    const parsed = loginSchema.safeParse({ email, password });
    if (!parsed.success) {
      const nextErrors: Record<string, string> = {};
      for (const issue of parsed.error.issues) {
        const field = issue.path[0];
        if (typeof field === "string" && !nextErrors[field]) {
          nextErrors[field] = issue.message;
        }
      }
      setFieldErrors(nextErrors);
      return;
    }
    setFieldErrors({});
    setSubmitting(true);
    try {
      const me = await signIn(parsed.data);
      router.replace(resolvePostAuthRedirect(returnUrl, me.role));
    } catch {
      // Error surfaced via provider state.
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2 text-center sm:text-left">
        <h1 className="text-[length:var(--font-size-2xl)] font-[var(--font-weight-bold)] text-[var(--color-text-primary)]">
          Sign in
        </h1>
        <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
          Use your email and password to access participant and organizer areas.
        </p>
      </div>

      {error ? (
        <EmptyFailureBlock
          variant="failure"
          title="Sign-in failed"
          description={error}
        />
      ) : null}

      <form
        className="space-y-4"
        noValidate
        onSubmit={(event) => void handleSubmit(event)}
      >
        <Field
          id="login-email"
          label="Email"
          required
          errorText={fieldErrors.email}
        >
          <Input
            id="login-email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={submitting}
            aria-invalid={Boolean(fieldErrors.email)}
          />
        </Field>
        <Field
          id="login-password"
          label="Password"
          required
          errorText={fieldErrors.password}
        >
          <Input
            id="login-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={submitting}
            aria-invalid={Boolean(fieldErrors.password)}
          />
        </Field>
        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </Button>
      </form>

      <p className="text-center text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
        New here?{" "}
        <Link
          href={
            returnUrl
              ? `/signup?returnUrl=${encodeURIComponent(returnUrl)}`
              : "/signup"
          }
          className="font-[var(--font-weight-medium)] text-[var(--color-action-primary-bg)] underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-action-focus-ring)]"
        >
          Create an account
        </Link>
      </p>
    </div>
  );
}
