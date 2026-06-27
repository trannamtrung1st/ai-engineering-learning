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
