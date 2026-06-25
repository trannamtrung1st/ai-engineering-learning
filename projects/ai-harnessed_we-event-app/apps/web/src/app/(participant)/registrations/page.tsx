"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, ClipboardCheck, MessageSquare, ShieldCheck } from "lucide-react";
import type { RegistrationState } from "@we-event/domain";

import { RegistrationStateBadge } from "@/components/participant/registration-state-badge";
import { FilterBar } from "@/components/layout/filter-bar";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Pagination } from "@/components/ui/pagination";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useLiveQuery } from "@/hooks/use-live-query";
import { registrationStateLabel } from "@/lib/domain-labels";
import { formatDateTime } from "@/lib/format";
import { fetchMyRegistrations } from "@/lib/participant-api";
import { queryKeys } from "@/lib/query-keys";
import { useAuth } from "@/providers/auth-provider";

const REGISTRATION_PAGE_SIZE = 20;

const REGISTRATION_STATE_FILTERS: Array<{
  value: "all" | RegistrationState;
  label: string;
}> = [
  { value: "all", label: "All statuses" },
  { value: "Registered", label: "Registered" },
  { value: "Waitlisted", label: "Waitlisted" },
  { value: "CheckedIn", label: "Checked in" },
  { value: "Attended", label: "Attended" },
  { value: "Rejected", label: "Rejected" },
  { value: "CancelledByUser", label: "Cancelled" },
];

function showCheckInLink(state: RegistrationState): boolean {
  return state === "Registered" || state === "CheckedIn";
}

function showFeedbackLink(state: RegistrationState): boolean {
  return state === "Attended";
}

function showEligibilityLink(state: RegistrationState): boolean {
  return state === "Attended" || state === "Absent" || state === "CheckedIn";
}

export default function MyRegistrationsPage() {
  const { token } = useAuth();
  const [page, setPage] = useState(1);
  const [stateFilter, setStateFilter] = useState<"all" | RegistrationState>("all");

  useEffect(() => {
    setPage(1);
  }, [stateFilter]);

  const listParams = useMemo(
    () => ({
      page,
      pageSize: REGISTRATION_PAGE_SIZE,
      state: stateFilter === "all" ? undefined : stateFilter,
    }),
    [page, stateFilter],
  );

  const registrationsQuery = useLiveQuery({
    queryKey: queryKeys.registrations.mine(listParams),
    queryFn: () => fetchMyRegistrations(token!, listParams),
    mode: "eventList",
    enabled: Boolean(token),
  });

  const items = useMemo(
    () => registrationsQuery.data?.items ?? [],
    [registrationsQuery.data?.items],
  );
  const total = registrationsQuery.data?.total ?? 0;
  const totalPages = registrationsQuery.data?.totalPages ?? 1;
  const pageSize = registrationsQuery.data?.pageSize ?? REGISTRATION_PAGE_SIZE;

  return (
    <div className="space-y-8">
      <PageHeader
        title="My registrations"
        subtitle="Current and past registrations with quick access to check-in and feedback."
      />

      <FilterBar>
        <Field id="registration-state-filter" label="Status" className="min-w-[12rem]">
          <Select
            value={stateFilter}
            onValueChange={(value) =>
              setStateFilter(value as "all" | RegistrationState)
            }
          >
            <SelectTrigger
              id="registration-state-filter"
              aria-label="Filter by registration status"
            >
              <SelectValue placeholder="All statuses" />
            </SelectTrigger>
            <SelectContent>
              {REGISTRATION_STATE_FILTERS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </FilterBar>

      {registrationsQuery.isLoading ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-36 w-full" />
          ))}
        </div>
      ) : null}

      {registrationsQuery.isError ? (
        <EmptyFailureBlock
          variant="failure"
          title="Could not load registrations"
          description={registrationsQuery.error.message}
          actionLabel="Retry"
          onAction={() => void registrationsQuery.refetch()}
        />
      ) : null}

      {registrationsQuery.isSuccess && items.length === 0 ? (
        <EmptyFailureBlock
          variant="empty"
          title={
            stateFilter === "all" ? "No registrations yet" : "No matching registrations"
          }
          description={
            stateFilter === "all"
              ? "Browse published events and register when registration is open."
              : "Try choosing a different status filter."
          }
          actionLabel={stateFilter === "all" ? "Browse events" : "Clear filter"}
          onAction={() => {
            if (stateFilter === "all") {
              window.location.href = "/events";
            } else {
              setStateFilter("all");
              setPage(1);
            }
          }}
        />
      ) : null}

      {registrationsQuery.isSuccess && items.length > 0 ? (
        <>
          <ul className="space-y-4">
            {items.map((item) => {
              const statusLabel = registrationStateLabel(item.state);

              return (
                <li
                  key={item.registrationId}
                  className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-6"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1">
                      <Link
                        href={`/events/${item.eventId}`}
                        className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-action-focus-ring)]"
                      >
                        {item.eventName}
                      </Link>
                      <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
                        Registration updated {formatDateTime(item.updatedAt)}
                      </p>
                    </div>
                    <RegistrationStateBadge state={item.state} />
                  </div>

                  {statusLabel.hint ? (
                    <p className="mt-3 text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
                      {statusLabel.hint}
                    </p>
                  ) : null}

                  <div className="mt-4 flex flex-wrap gap-2">
                    {showCheckInLink(item.state) ? (
                      <Button asChild size="sm" variant="secondary">
                        <Link href={`/events/${item.eventId}/check-in`}>
                          <ClipboardCheck className="h-4 w-4" aria-hidden />
                          Check in
                        </Link>
                      </Button>
                    ) : null}

                    {showFeedbackLink(item.state) ? (
                      <Button asChild size="sm" variant="secondary">
                        <Link href={`/events/${item.eventId}/feedback`}>
                          <MessageSquare className="h-4 w-4" aria-hidden />
                          Feedback
                        </Link>
                      </Button>
                    ) : null}

                    {showEligibilityLink(item.state) ? (
                      <Button asChild size="sm" variant="ghost">
                        <Link href={`/events/${item.eventId}/eligibility`}>
                          <ShieldCheck className="h-4 w-4" aria-hidden />
                          Eligibility
                        </Link>
                      </Button>
                    ) : null}

                    <Button asChild size="sm" variant="ghost">
                      <Link href={`/events/${item.eventId}`}>
                        Event details
                        <ArrowRight className="h-4 w-4" aria-hidden />
                      </Link>
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>

          <Pagination
            page={page}
            pageCount={Math.max(totalPages, 1)}
            total={total}
            pageSize={pageSize}
            onPageChange={setPage}
          />
        </>
      ) : null}
    </div>
  );
}
