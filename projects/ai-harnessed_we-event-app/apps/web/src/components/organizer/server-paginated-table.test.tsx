import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import { ServerPaginatedTable } from "./server-paginated-table.js";

describe("ServerPaginatedTable", () => {
  const auditRows = [
    {
      id: "audit-1",
      occurredAt: "2026-06-15T12:00:00.000Z",
      action: "RULE_CONFIG_UPDATED",
      entityType: "EventRuleConfig",
      entityId: "cfg-1",
      actorId: "00000000-0000-0000-0000-000000000099",
      actorRole: "OrganizerAdmin",
      reasonCode: "CAPACITY_CHANGE",
      reasonText: "Increased capacity for demand",
    },
  ];

  const eligibilityRows = [
    {
      registrationId: "reg-1",
      participantId: "participant-1",
      registrationState: "Attended",
      eligibility: {
        result: "Eligible" as const,
        reasonText: "Attended and feedback submitted",
        evaluatedAt: "2026-06-16T10:00:00.000Z",
        overriddenBy: null,
      },
    },
  ];

  it("AC-14: renders server-driven pagination metadata for operational tables", () => {
    const html = renderToStaticMarkup(
      <ServerPaginatedTable
        columns={[
          { id: "name", header: "Event", cell: (row: { name: string }) => row.name },
        ]}
        items={[{ name: "Summit" }]}
        rowKey={(row) => row.name}
        page={2}
        pageSize={20}
        total={45}
        totalPages={3}
        onPageChange={() => {}}
      />,
    );
    assert.match(html, /Page 2 of 3/);
    assert.match(html, /Showing 21–40 of 45/);
  });

  it("AC-11: surfaces audit actor, action, and reason columns", () => {
    const html = renderToStaticMarkup(
      <ServerPaginatedTable
        columns={[
          { id: "action", header: "Action", cell: (row) => row.action },
          { id: "actor", header: "Actor", cell: (row) => row.actorId },
          {
            id: "reason",
            header: "Reason",
            cell: (row) => row.reasonText ?? row.reasonCode ?? "—",
          },
        ]}
        items={auditRows}
        rowKey={(row) => row.id}
        page={1}
        pageSize={20}
        total={1}
        totalPages={1}
        onPageChange={() => {}}
      />,
    );
    assert.match(html, /RULE_CONFIG_UPDATED/);
    assert.match(html, /00000000-0000-0000-0000-000000000099/);
    assert.match(html, /Increased capacity for demand/);
  });

  const registrationRows = [
    {
      registrationId: "reg-wl-1",
      participantId: "participant-wait-1",
      state: "Waitlisted" as const,
      waitlistPosition: 2,
      updatedAt: "2026-06-27T10:00:00.000Z",
      reasonText: null,
    },
    {
      registrationId: "reg-reg-1",
      participantId: "participant-reg-1",
      state: "Registered" as const,
      waitlistPosition: null,
      updatedAt: "2026-06-27T11:00:00.000Z",
      reasonText: null,
    },
  ];

  const attendanceRows = [
    {
      registrationId: "reg-checkin-1",
      participantId: "participant-checkin-1",
      state: "CheckedIn",
      checkinAt: "2026-06-27T12:26:00.000Z",
      checkinMethod: "Staff" as const,
    },
    {
      registrationId: "reg-pending-1",
      participantId: "participant-pending-1",
      state: "Registered",
      checkinAt: null,
      checkinMethod: null,
    },
  ];

  it("FR-12 / AC-13: surfaces waitlist position for Waitlisted registration rows", () => {
    const html = renderToStaticMarkup(
      <ServerPaginatedTable
        columns={[
          { id: "participant", header: "Participant", cell: (row) => row.participantId },
          { id: "state", header: "Status", cell: (row) => row.state },
          {
            id: "waitlist",
            header: "Waitlist #",
            cell: (row) => row.waitlistPosition ?? "—",
          },
        ]}
        items={registrationRows}
        rowKey={(row) => row.registrationId}
        page={1}
        pageSize={20}
        total={2}
        totalPages={1}
        onPageChange={() => {}}
      />,
    );
    assert.match(html, /Waitlisted/);
    assert.match(html, />2</);
    assert.match(html, /participant-wait-1/);
  });

  it("AC-05 / FR-13: surfaces staff check-in timestamp and method in attendance rows", () => {
    const html = renderToStaticMarkup(
      <ServerPaginatedTable
        columns={[
          { id: "participant", header: "Participant", cell: (row) => row.participantId },
          {
            id: "checkin",
            header: "Check-in",
            cell: (row) =>
              row.checkinAt
                ? `${row.checkinAt} · ${row.checkinMethod ?? ""}`
                : "Not checked in",
          },
        ]}
        items={attendanceRows}
        rowKey={(row) => row.registrationId}
        page={1}
        pageSize={20}
        total={2}
        totalPages={1}
        onPageChange={() => {}}
      />,
    );
    assert.match(html, /2026-06-27T12:26:00.000Z · Staff/);
    assert.match(html, /Not checked in/);
  });

  it("AC-10: surfaces eligibility reason text in operational rows", () => {
    const html = renderToStaticMarkup(
      <ServerPaginatedTable
        columns={[
          {
            id: "result",
            header: "Eligibility",
            cell: (row) => row.eligibility.result,
          },
          {
            id: "reason",
            header: "Reason",
            cell: (row) => row.eligibility.reasonText ?? "—",
          },
        ]}
        items={eligibilityRows}
        rowKey={(row) => row.registrationId}
        page={1}
        pageSize={20}
        total={1}
        totalPages={1}
        onPageChange={() => {}}
      />,
    );
    assert.match(html, /Eligible/);
    assert.match(html, /Attended and feedback submitted/);
  });
});
