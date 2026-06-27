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

const signupSchema = z.object({
  email: z.string().email("Enter a valid email address."),
  password: z
    .string()
    .min(8, "Password must be at least 8 characters."),
  displayName: z.string().trim().min(1, "Display name is required."),
});

export function SignupPageClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const returnUrl = searchParams.get("returnUrl");
  const { token, session, isLoading, error, register, clearError } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
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
    const parsed = signupSchema.safeParse({ email, password, displayName });
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
      const me = await register(parsed.data);
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
          Create account
        </h1>
        <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
          Register as a participant to browse events, register, check in, and
          submit feedback.
        </p>
      </div>

      {error ? (
        <EmptyFailureBlock
          variant="failure"
          title="Sign-up failed"
          description={error}
        />
      ) : null}

      <form
        className="space-y-4"
        noValidate
        onSubmit={(event) => void handleSubmit(event)}
      >
        <Field
          id="signup-display-name"
          label="Display name"
          required
          errorText={fieldErrors.displayName}
        >
          <Input
            id="signup-display-name"
            autoComplete="name"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            disabled={submitting}
            aria-invalid={Boolean(fieldErrors.displayName)}
          />
        </Field>
        <Field
          id="signup-email"
          label="Email"
          required
          errorText={fieldErrors.email}
        >
          <Input
            id="signup-email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={submitting}
            aria-invalid={Boolean(fieldErrors.email)}
          />
        </Field>
        <Field
          id="signup-password"
          label="Password"
          required
          helperText="At least 8 characters."
          errorText={fieldErrors.password}
        >
          <Input
            id="signup-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={submitting}
            aria-invalid={Boolean(fieldErrors.password)}
          />
        </Field>
        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </Button>
      </form>

      <p className="text-center text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
        Already have an account?{" "}
        <Link
          href={
            returnUrl
              ? `/login?returnUrl=${encodeURIComponent(returnUrl)}`
              : "/login"
          }
          className="font-[var(--font-weight-medium)] text-[var(--color-action-primary-bg)] underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-action-focus-ring)]"
        >
          Sign in
        </Link>
      </p>
    </div>
  );
}
