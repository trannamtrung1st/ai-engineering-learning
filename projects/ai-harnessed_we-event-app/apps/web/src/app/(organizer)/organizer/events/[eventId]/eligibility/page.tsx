"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import type { CertificateEligibilityState, RegistrationState } from "@we-event/domain";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { EligibilityStateBadge } from "@/components/participant/eligibility-state-badge";
import { RegistrationStateBadge } from "@/components/participant/registration-state-badge";
import { ServerPaginatedTable } from "@/components/organizer/server-paginated-table";
import { PageHeader } from "@/components/layout/page-header";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { useLiveQuery } from "@/hooks/use-live-query";
import { ApiClientError } from "@/lib/api-client";
import { formatDateTime } from "@/lib/format";
import {
  downloadEligibilityExport,
  fetchEligibility,
  revokeEligibility,
} from "@/lib/organizer-api";
import { queryKeys } from "@/lib/query-keys";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

const PAGE_SIZE = 20;

const ELIGIBILITY_FILTERS: Array<{
  value: "all" | CertificateEligibilityState;
  label: string;
}> = [
  { value: "all", label: "All" },
  { value: "Eligible", label: "Eligible" },
  { value: "NotEligible", label: "Not eligible" },
  { value: "PendingEvaluation", label: "Pending" },
  { value: "Revoked", label: "Revoked" },
];

export default function EventEligibilityPage() {
  const params = useParams<{ eventId: string }>();
  const eventId = params.eventId;
  const { token, isAdmin } = useOrganizerAuth();
  const queryClient = useQueryClient();
  const { push } = useToast();
  const [page, setPage] = useState(1);
  const [segment, setSegment] = useState<"all" | CertificateEligibilityState>(
    "all",
  );
  const [revokeTarget, setRevokeTarget] = useState<string | null>(null);
  const [reasonCode, setReasonCode] = useState("ORGANIZER_REVOKE");
  const [reasonText, setReasonText] = useState("");
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    setPage(1);
  }, [segment]);

  const listParams = useMemo(
    () => ({
      page,
      pageSize: PAGE_SIZE,
      eligibility: segment === "all" ? undefined : segment,
    }),
    [page, segment],
  );

  const query = useLiveQuery({
    queryKey: queryKeys.organizer.eligibility(eventId, listParams),
    queryFn: () => fetchEligibility(token!, eventId, listParams),
    mode: "organizerDashboard",
    enabled: Boolean(token),
  });

  const revokeMutation = useMutation({
    mutationFn: (registrationId: string) =>
      revokeEligibility(token!, eventId, registrationId, {
        reasonCode: reasonCode.trim(),
        reasonText: reasonText.trim(),
      }),
    onSuccess: () => {
      setRevokeTarget(null);
      setReasonText("");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.organizer.eligibility(eventId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.organizer.dashboard(eventId),
      });
      push({
        title: "Eligibility revoked",
        description: "The revocation is recorded in the audit log.",
        variant: "success",
      });
    },
    onError: (error) => {
      push({
        title: "Revocation failed",
        description:
          error instanceof ApiClientError ? error.message : "Try again.",
        variant: "error",
      });
    },
  });

  const items = query.data?.items ?? [];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Eligibility"
        subtitle="Review certificate eligibility outcomes with reason visibility."
        actions={
          <Button
            size="sm"
            variant="secondary"
            loading={exporting}
            disabled={exporting}
            onClick={async () => {
              setExporting(true);
              try {
                const result = await downloadEligibilityExport(token!, eventId, {
                  eligibility: segment === "all" ? undefined : segment,
                });
                push({
                  title: "Export ready",
                  description:
                    result.rowCount > 0
                      ? `Downloaded ${result.rowCount} eligibility rows.`
                      : `Downloaded ${result.filename}.`,
                  variant: "success",
                });
              } catch (error) {
                push({
                  title: "Export failed",
                  description:
                    error instanceof ApiClientError ? error.message : "Try again.",
                  variant: "error",
                });
              } finally {
                setExporting(false);
              }
            }}
          >
            Export CSV
          </Button>
        }
      />

      <Tabs
        value={segment}
        onValueChange={(value) =>
          setSegment(value as "all" | CertificateEligibilityState)
        }
      >
        <TabsList>
          {ELIGIBILITY_FILTERS.map((filter) => (
            <TabsTrigger key={filter.value} value={filter.value}>
              {filter.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value={segment} className="mt-6">
          <ServerPaginatedTable
            columns={[
              {
                id: "participant",
                header: "Participant",
                cell: (row) => row.participantId,
              },
              {
                id: "registration",
                header: "Registration",
                cell: (row) => (
                  <RegistrationStateBadge
                    state={row.registrationState as RegistrationState}
                  />
                ),
              },
              {
                id: "result",
                header: "Eligibility",
                cell: (row) => (
                  <EligibilityStateBadge state={row.eligibility.result} />
                ),
              },
              {
                id: "reason",
                header: "Reason",
                cell: (row) => row.eligibility.reasonText ?? "—",
              },
              {
                id: "evaluated",
                header: "Evaluated",
                cell: (row) => formatDateTime(row.eligibility.evaluatedAt),
              },
              {
                id: "override",
                header: "Override",
                cell: (row) => row.eligibility.overriddenBy ?? "—",
              },
              {
                id: "actions",
                header: "",
                cell: (row) =>
                  isAdmin && row.eligibility.result === "Eligible" ? (
                    <Button
                      size="sm"
                      variant="danger"
                      onClick={() => setRevokeTarget(row.registrationId)}
                    >
                      Revoke
                    </Button>
                  ) : null,
              },
            ]}
            items={items}
            rowKey={(row) => row.registrationId}
            page={page}
            pageSize={query.data?.pageSize ?? PAGE_SIZE}
            total={query.data?.total ?? 0}
            totalPages={query.data?.totalPages ?? 1}
            onPageChange={setPage}
            isLoading={query.isLoading}
            isError={query.isError}
            errorMessage={query.error?.message}
            emptyTitle="No eligibility rows"
            emptyDescription="Outcomes appear after feedback and attendance are recorded."
          />
        </TabsContent>
      </Tabs>

      <Dialog open={Boolean(revokeTarget)} onOpenChange={() => setRevokeTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revoke eligibility</DialogTitle>
            <DialogDescription>
              Revocation requires a reason code and explanation for the audit log.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <Field id="revoke-reason-code" label="Reason code" required>
              <Input
                id="revoke-reason-code"
                value={reasonCode}
                onChange={(event) => setReasonCode(event.target.value)}
              />
            </Field>
            <Field id="revoke-reason-text" label="Reason" required>
              <Textarea
                id="revoke-reason-text"
                value={reasonText}
                onChange={(event) => setReasonText(event.target.value)}
                rows={3}
              />
            </Field>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setRevokeTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={revokeMutation.isPending}
              disabled={!reasonCode.trim() || !reasonText.trim()}
              onClick={() => {
                if (revokeTarget) {
                  revokeMutation.mutate(revokeTarget);
                }
              }}
            >
              Revoke eligibility
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
