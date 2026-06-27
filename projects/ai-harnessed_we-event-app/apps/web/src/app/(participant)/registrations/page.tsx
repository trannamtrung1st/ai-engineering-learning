"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, ClipboardCheck, MessageSquare, ShieldCheck } from "lucide-react";
import type { RegistrationState } from "@we-event/domain";

import { RegistrationStatusTimeline } from "@/components/participant/registration-status-timeline";
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
import { fetchMyRegistrations } from "@/lib/participant-api";
import { deriveMyRegistrationQuickActions } from "@/lib/my-registration-actions";
import { queryKeys } from "@/lib/query-keys";
import { useAuth } from "@/providers/auth-provider";

const REGISTRATION_PAGE_SIZE = 20;

const REGISTRATION_SORT_OPTIONS = [
  { value: "updatedAt:desc", label: "Recently updated" },
  { value: "requestedAt:asc", label: "Request date (oldest first)" },
] as const;

type RegistrationSort = (typeof REGISTRATION_SORT_OPTIONS)[number]["value"];

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

export default function MyRegistrationsPage() {
  const { token } = useAuth();
  const [page, setPage] = useState(1);
  const [stateFilter, setStateFilter] = useState<"all" | RegistrationState>("all");
  const [sort, setSort] = useState<RegistrationSort>("updatedAt:desc");

  useEffect(() => {
    setPage(1);
  }, [stateFilter, sort]);

  const listParams = useMemo(
    () => ({
      page,
      pageSize: REGISTRATION_PAGE_SIZE,
      state: stateFilter === "all" ? undefined : stateFilter,
      sort,
    }),
    [page, stateFilter, sort],
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
        <Field id="registration-sort" label="Sort by" className="min-w-[12rem]">
          <Select value={sort} onValueChange={(value) => setSort(value as RegistrationSort)}>
            <SelectTrigger id="registration-sort" aria-label="Sort by">
              <SelectValue placeholder="Recently updated" />
            </SelectTrigger>
            <SelectContent>
              {REGISTRATION_SORT_OPTIONS.map((option) => (
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
            stateFilter === "all" ? "No registrations yet" : "No registrations match this status"
          }
          description={
            stateFilter === "all"
              ? "Browse published events and register when registration is open."
              : "Try choosing a different status filter or reset the filter."
          }
          actionLabel={stateFilter === "all" ? "Browse events" : "Clear filter"}
          onAction={() => {
            if (stateFilter === "all") {
              window.location.href = "/events";
            } else {
              setStateFilter("all");
              setSort("updatedAt:desc");
              setPage(1);
            }
          }}
        />
      ) : null}

      {registrationsQuery.isSuccess && items.length > 0 ? (
        <>
          <ul className="space-y-4">
            {items.map((item) => {
              const quickActions = deriveMyRegistrationQuickActions(item);
              return (
                <li
                  key={item.registrationId}
                  className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-6"
                >
                  <div className="space-y-1">
                    <Link
                      href={`/events/${item.eventId}`}
                      className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-action-focus-ring)]"
                    >
                      {item.eventName}
                    </Link>
                  </div>

                  <div className="mt-4">
                    <RegistrationStatusTimeline
                      state={item.state}
                      updatedAt={item.updatedAt}
                      waitlistPosition={item.waitlistPosition}
                      reasonText={item.reasonText}
                    />
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    {quickActions.showCheckIn ? (
                      <Button asChild size="sm" variant="secondary">
                        <Link href={`/events/${item.eventId}/check-in`}>
                          <ClipboardCheck className="h-4 w-4" aria-hidden />
                          Check in
                        </Link>
                      </Button>
                    ) : null}

                    {quickActions.showFeedback ? (
                      <Button asChild size="sm" variant="secondary">
                        <Link href={`/events/${item.eventId}/feedback`}>
                          <MessageSquare className="h-4 w-4" aria-hidden />
                          Feedback
                        </Link>
                      </Button>
                    ) : null}

                    {quickActions.showEligibility ? (
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
