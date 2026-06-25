"use client";

import { useState } from "react";
import type { EventState } from "@we-event/domain";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { EventStateBadge } from "@/components/participant/event-state-badge";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";
import { ApiClientError } from "@/lib/api-client";
import {
  cancelEvent,
  closeRegistration,
  completeEvent,
  openRegistration,
  pauseEvent,
  publishEvent,
  startEvent,
  type EventSummary,
} from "@/lib/organizer-api";
import { queryKeys } from "@/lib/query-keys";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

interface EventLifecycleActionsProps {
  event: EventSummary;
}

export function EventLifecycleActions({ event }: EventLifecycleActionsProps) {
  const { token } = useOrganizerAuth();
  const queryClient = useQueryClient();
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.organizer.events.detail(event.eventId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.organizer.events.listRoot(),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.organizer.dashboard(event.eventId),
    });
  };

  const mutation = useMutation({
    mutationFn: async (action: () => Promise<EventSummary>) => action(),
    onSuccess: () => {
      setActionError(null);
      invalidate();
    },
    onError: (error) => {
      setActionError(
        error instanceof ApiClientError
          ? error.message
          : "Action could not be completed.",
      );
    },
  });

  const actions = availableActions(event.state, event.ruleConfig.registrationPaused);

  return (
    <div className="space-y-4 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
            Lifecycle
          </p>
          <EventStateBadge state={event.state} />
        </div>
        <div className="flex flex-wrap gap-2">
          {actions.map((action) => (
            <Button
              key={action.id}
              size="sm"
              variant={action.variant}
              disabled={mutation.isPending}
              onClick={() => {
                if (action.id === "cancel") {
                  setCancelOpen(true);
                  return;
                }
                mutation.mutate(() => action.run(token!, event.eventId));
              }}
            >
              {action.label}
            </Button>
          ))}
        </div>
      </div>

      {event.ruleConfig.registrationPaused ? (
        <Alert variant="warning" title="Registration paused">
          New registrations are paused while the event remains in an open registration
          state.
        </Alert>
      ) : null}

      {actionError ? (
        <Alert variant="error" title="Action blocked">
          {actionError}
        </Alert>
      ) : null}

      <Dialog open={cancelOpen} onOpenChange={setCancelOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel event</DialogTitle>
            <DialogDescription>
              Cancelling is irreversible for participants. Provide a reason that will
              be recorded in the audit log.
            </DialogDescription>
          </DialogHeader>
          <Field id="cancel-reason" label="Reason" required>
            <Textarea
              id="cancel-reason"
              value={cancelReason}
              onChange={(event) => setCancelReason(event.target.value)}
              rows={3}
            />
          </Field>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setCancelOpen(false)}>
              Keep event
            </Button>
            <Button
              variant="danger"
              disabled={!cancelReason.trim() || mutation.isPending}
              onClick={() => {
                mutation.mutate(() =>
                  cancelEvent(token!, event.eventId, cancelReason.trim()),
                );
                setCancelOpen(false);
              }}
            >
              Cancel event
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function availableActions(
  state: EventState,
  registrationPaused: boolean,
): Array<{
  id: string;
  label: string;
  variant: "primary" | "secondary" | "danger";
  run: (token: string, eventId: string) => Promise<EventSummary>;
}> {
  const list: Array<{
    id: string;
    label: string;
    variant: "primary" | "secondary" | "danger";
    run: (token: string, eventId: string) => Promise<EventSummary>;
  }> = [];

  if (state === "Draft") {
    list.push({
      id: "publish",
      label: "Publish",
      variant: "primary",
      run: publishEvent,
    });
  }

  if (state === "Published") {
    list.push({
      id: "open-registration",
      label: "Open registration",
      variant: "primary",
      run: openRegistration,
    });
  }

  if (state === "RegistrationOpen" && !registrationPaused) {
    list.push({
      id: "pause",
      label: "Pause registration",
      variant: "secondary",
      run: pauseEvent,
    });
    list.push({
      id: "close-registration",
      label: "Close registration",
      variant: "secondary",
      run: closeRegistration,
    });
  }

  if (state === "RegistrationClosed") {
    list.push({
      id: "start",
      label: "Start event",
      variant: "primary",
      run: startEvent,
    });
  }

  if (state === "InProgress") {
    list.push({
      id: "complete",
      label: "Complete event",
      variant: "primary",
      run: completeEvent,
    });
  }

  if (state !== "Cancelled" && state !== "Archived" && state !== "Completed") {
    list.push({
      id: "cancel",
      label: "Cancel event",
      variant: "danger",
      run: () => Promise.reject(new Error("Use cancel dialog")),
    });
  }

  return list;
}
