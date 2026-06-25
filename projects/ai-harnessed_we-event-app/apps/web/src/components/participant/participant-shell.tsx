"use client";

import { type ReactNode, useState } from "react";

import { ParticipantNav } from "@/components/participant/participant-nav";
import { AppShell } from "@/components/layout/app-shell";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/providers/auth-provider";

export function ParticipantShell({ children }: { children: ReactNode }) {
  const { token, session, isLoading, error, signIn, signOut } = useAuth();
  const [participantId, setParticipantId] = useState("participant-1");
  const [signingIn, setSigningIn] = useState(false);

  if (isLoading) {
    return (
      <AppShell role="participant" userDisplayName="Loading…">
        <div className="space-y-4">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-40 w-full" />
        </div>
      </AppShell>
    );
  }

  if (!token || !session) {
    return (
      <AppShell role="participant" userDisplayName="Guest">
        <div className="mx-auto max-w-md space-y-6">
          <div className="space-y-2">
            <h1 className="text-[length:var(--font-size-2xl)] font-[var(--font-weight-bold)] text-[var(--color-text-primary)]">
              Sign in
            </h1>
            <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
              Use a participant ID to access events. Local development uses the dev
              token endpoint when enabled on the API.
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
            onSubmit={(event) => {
              event.preventDefault();
              setSigningIn(true);
              void signIn(participantId).finally(() => setSigningIn(false));
            }}
          >
            <Field id="participant-id" label="Participant ID" required>
              <Input
                id="participant-id"
                value={participantId}
                onChange={(event) => setParticipantId(event.target.value)}
                autoComplete="username"
                disabled={signingIn}
              />
            </Field>
            <Button type="submit" disabled={signingIn}>
              {signingIn ? "Signing in…" : "Continue"}
            </Button>
          </form>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell role="participant" userDisplayName={session.actorId}>
      <ParticipantNav />
      <div className="mt-6">{children}</div>
      <div className="sr-only">
        <button type="button" onClick={signOut}>
          Sign out
        </button>
      </div>
    </AppShell>
  );
}
