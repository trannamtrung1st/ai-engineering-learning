"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import type { RegistrationState } from "@we-event/domain";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { RegistrationStateBadge } from "@/components/participant/registration-state-badge";
import { ServerPaginatedTable } from "@/components/organizer/server-paginated-table";
import { PageHeader } from "@/components/layout/page-header";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useLiveQuery } from "@/hooks/use-live-query";
import { ApiClientError } from "@/lib/api-client";
import { formatDateTime } from "@/lib/format";
import {
  fetchAttendance,
  fetchOrganizerEvent,
  staffCheckin,
} from "@/lib/organizer-api";
import { queryKeys } from "@/lib/query-keys";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

const PAGE_SIZE = 20;

export default function EventCheckInConsolePage() {
  const params = useParams<{ eventId: string }>();
  const eventId = params.eventId;
  const { token } = useOrganizerAuth();
  const queryClient = useQueryClient();
  const { push } = useToast();
  const [page, setPage] = useState(1);
  const [actionError, setActionError] = useState<string | null>(null);

  const listParams = useMemo(() => ({ page, pageSize: PAGE_SIZE }), [page]);

  const eventQuery = useLiveQuery({
    queryKey: queryKeys.organizer.events.detail(eventId),
    queryFn: () => fetchOrganizerEvent(token!, eventId),
    mode: "checkInConsole",
    enabled: Boolean(token),
  });

  const attendanceQuery = useLiveQuery({
    queryKey: queryKeys.organizer.attendance(eventId, listParams),
    queryFn: () => fetchAttendance(token!, eventId, listParams),
    mode: "checkInConsole",
    enabled: Boolean(token),
  });

  const checkinMutation = useMutation({
    mutationFn: (registrationId: string) =>
      staffCheckin(token!, eventId, registrationId),
    onSuccess: (result) => {
      setActionError(null);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.organizer.attendance(eventId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.organizer.dashboard(eventId),
      });
      push({
        title: "Check-in recorded",
        description: `${result.participantId} checked in at ${formatDateTime(result.checkinAt)} (${result.method}).`,
        variant: "success",
      });
    },
    onError: (error) => {
      const message =
        error instanceof ApiClientError
          ? error.message
          : "Staff check-in could not be completed.";
      setActionError(message);
    },
  });

  const event = eventQuery.data;
  const items = attendanceQuery.data?.items ?? [];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Check-in console"
        subtitle="Staff check-in with audit metadata (method, actor, timestamp)."
      />

      {event ? (
        <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
          Check-in window: {formatDateTime(event.ruleConfig.checkinOpenAt)} –{" "}
          {formatDateTime(event.ruleConfig.checkinCloseAt)}
        </p>
      ) : null}

      {actionError ? (
        <Alert variant="error" title="Check-in blocked">
          {actionError}
        </Alert>
      ) : null}

      <ServerPaginatedTable
        columns={[
          {
            id: "participant",
            header: "Participant",
            cell: (row) => row.participantId,
          },
          {
            id: "state",
            header: "Registration",
            cell: (row) => (
              <RegistrationStateBadge state={row.state as RegistrationState} />
            ),
          },
          {
            id: "checkin",
            header: "Check-in",
            cell: (row) =>
              row.checkinAt ? (
                <span>
                  {formatDateTime(row.checkinAt)}
                  {row.checkinMethod ? ` · ${row.checkinMethod}` : ""}
                </span>
              ) : (
                "Not checked in"
              ),
          },
          {
            id: "actions",
            header: "",
            cell: (row) =>
              row.checkinAt ? null : row.state === "Registered" ? (
                <Button
                  size="sm"
                  variant="secondary"
                  loading={checkinMutation.isPending}
                  onClick={() => checkinMutation.mutate(row.registrationId)}
                >
                  Check in
                </Button>
              ) : (
                <span className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
                  Not eligible
                </span>
              ),
          },
        ]}
        items={items}
        rowKey={(row) => row.registrationId}
        page={page}
        pageSize={attendanceQuery.data?.pageSize ?? PAGE_SIZE}
        total={attendanceQuery.data?.total ?? 0}
        totalPages={attendanceQuery.data?.totalPages ?? 1}
        onPageChange={setPage}
        isLoading={attendanceQuery.isLoading}
        isError={attendanceQuery.isError}
        errorMessage={attendanceQuery.error?.message}
        emptyTitle="No attendance rows"
        emptyDescription="Registrations will appear here for check-in tracking."
      />
    </div>
  );
}
