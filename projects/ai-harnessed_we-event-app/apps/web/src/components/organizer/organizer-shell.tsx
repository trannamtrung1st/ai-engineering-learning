"use client";

import { type ReactNode, useState } from "react";

import { AppShell } from "@/components/layout/app-shell";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { organizerNavItems } from "@/lib/app-context";
import { DEFAULT_ORGANIZER_ADMIN_ID } from "@/lib/organizer-api";
import {
  useOrganizerAuth,
  type OrganizerRole,
} from "@/providers/organizer-auth-provider";

export function OrganizerShell({ children }: { children: ReactNode }) {
  const { token, session, isAdmin, isLoading, error, signIn, signOut } =
    useOrganizerAuth();
  const [organizerId, setOrganizerId] = useState(DEFAULT_ORGANIZER_ADMIN_ID);
  const [role, setRole] = useState<OrganizerRole>("OrganizerAdmin");
  const [assignedEvents, setAssignedEvents] = useState("");
  const [signingIn, setSigningIn] = useState(false);

  const appRole = isAdmin ? "organizer-admin" : "organizer-staff";

  if (isLoading) {
    return (
      <AppShell role="organizer-admin" userDisplayName="Loading…">
        <div className="space-y-4">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-40 w-full" />
        </div>
      </AppShell>
    );
  }

  if (!token || !session) {
    return (
      <AppShell role="organizer-admin" userDisplayName="Guest">
        <div className="mx-auto max-w-md space-y-6">
          <div className="space-y-2">
            <h1 className="text-[length:var(--font-size-2xl)] font-[var(--font-weight-bold)] text-[var(--color-text-primary)]">
              Organizer sign-in
            </h1>
            <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
              Sign in as an organizer admin or staff member. Local development uses
              the dev token endpoint when enabled on the API.
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
              const assigned = assignedEvents
                .split(",")
                .map((id) => id.trim())
                .filter(Boolean);
              void signIn(organizerId, role, assigned).finally(() =>
                setSigningIn(false),
              );
            }}
          >
            <Field id="organizer-id" label="Organizer ID" required>
              <Input
                id="organizer-id"
                value={organizerId}
                onChange={(event) => setOrganizerId(event.target.value)}
                disabled={signingIn}
              />
            </Field>
            <Field id="organizer-role" label="Role" required>
              <Select
                value={role}
                onValueChange={(value) => setRole(value as OrganizerRole)}
              >
                <SelectTrigger id="organizer-role">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="OrganizerAdmin">Organizer Admin</SelectItem>
                  <SelectItem value="OrganizerStaff">Organizer Staff</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            {role === "OrganizerStaff" ? (
              <Field
                id="assigned-events"
                label="Assigned event IDs"
                helperText="Comma-separated event UUIDs for staff scope."
              >
                <Input
                  id="assigned-events"
                  value={assignedEvents}
                  onChange={(event) => setAssignedEvents(event.target.value)}
                  placeholder="event-uuid-1, event-uuid-2"
                  disabled={signingIn}
                />
              </Field>
            ) : null}
            <Button type="submit" disabled={signingIn}>
              {signingIn ? "Signing in…" : "Continue"}
            </Button>
          </form>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell
      role={appRole}
      navItems={organizerNavItems}
      userDisplayName={session.actorId}
    >
      <div>{children}</div>
      <div className="sr-only">
        <button type="button" onClick={signOut}>
          Sign out
        </button>
      </div>
    </AppShell>
  );
}
