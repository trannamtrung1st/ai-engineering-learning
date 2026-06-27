"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { useToast } from "@/components/ui/toast";
import { ApiClientError } from "@/lib/api-client";
import { registrationStateLabel } from "@/lib/domain-labels";
import {
  cancelRegistration,
  registerForEvent,
  type EventSummary,
  type RegistrationStatus,
} from "@/lib/participant-api";
import { queryKeys } from "@/lib/query-keys";
import { useAuth } from "@/providers/auth-provider";

import {
  deriveRegistrationPanelState,
  RegistrationStatusPanelView,
} from "./registration-status-panel-view";

export interface RegistrationStatusPanelProps {
  eventId: string;
  event: EventSummary;
  registration: RegistrationStatus | null;
  isLoading?: boolean;
  isError?: boolean;
  error?: Error | null;
  onRetry?: () => void;
}

export function RegistrationStatusPanel({
  eventId,
  event,
  registration,
  isLoading = false,
  isError = false,
  error = null,
  onRetry,
}: RegistrationStatusPanelProps) {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const { push } = useToast();
  const [cancelDialogOpen, setCancelDialogOpen] = useState(false);

  const panelState = useMemo(
    () => deriveRegistrationPanelState(event, registration),
    [event, registration],
  );

  const invalidateRegistrationQueries = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.registrations.status(eventId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.registrations.mineAll() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.events.listRoot() });
  };

  const registerMutation = useMutation({
    mutationFn: () => registerForEvent(token!, eventId),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.registrations.status(eventId), {
        registration: result,
      });
      invalidateRegistrationQueries();
      const label = registrationStateLabel(result.state);
      push({
        title: "Registration submitted",
        description:
          result.state === "Waitlisted" && result.waitlistPosition
            ? `You are waitlisted at queue position ${result.waitlistPosition}.`
            : label.hint ?? `Your status is ${label.label}.`,
        variant: "success",
      });
    },
    onError: (err) => {
      push({
        title: "Registration failed",
        description: err instanceof Error ? err.message : "Try again.",
        variant: "error",
      });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelRegistration(token!, eventId, registration!.registrationId),
    onSuccess: (result) => {
      setCancelDialogOpen(false);
      queryClient.setQueryData(queryKeys.registrations.status(eventId), {
        registration: result.cancelled,
      });
      invalidateRegistrationQueries();
      push({
        title: "Registration cancelled",
        description: "Your registration has been cancelled.",
        variant: "success",
      });
      if (result.promoted) {
        push({
          title: "Waitlist promotion",
          description:
            "A waitlisted participant was automatically promoted to fill the released seat.",
          variant: "info",
        });
      }
    },
    onError: (err) => {
      push({
        title: "Cancellation failed",
        description: err instanceof Error ? err.message : "Try again.",
        variant: "error",
      });
    },
  });

  return (
    <RegistrationStatusPanelView
      registration={registration}
      isLoading={isLoading}
      isError={isError}
      error={error}
      onRetry={onRetry}
      {...panelState}
      registerPending={registerMutation.isPending}
      cancelPending={cancelMutation.isPending}
      registerError={
        registerMutation.isError
          ? registerMutation.error instanceof ApiClientError
            ? registerMutation.error.message
            : "Unable to register. Try again."
          : null
      }
      cancelError={
        cancelMutation.isError
          ? cancelMutation.error instanceof ApiClientError
            ? cancelMutation.error.message
            : "Unable to cancel. Try again."
          : null
      }
      cancelDialogOpen={cancelDialogOpen}
      onCancelDialogOpenChange={setCancelDialogOpen}
      onRegister={() => registerMutation.mutate()}
      onConfirmCancel={() => cancelMutation.mutate()}
    />
  );
}
