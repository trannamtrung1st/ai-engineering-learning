/**
 * Traceability: FR-19 FR-14 AC-02 NFR-16
 * TC-FR-19-002 TC-FR-19-003 TC-FR-14-003 TC-NFR-16-009
 */
import { describe, expect, it } from "vitest";
import {
  RealtimeDeliveryGateway,
  formatServerSentEvent,
} from "./event-gateway.js";
import type { RealtimeRosterEvent } from "./types.js";

function rosterEvent(): RealtimeRosterEvent {
  return {
    eventId: "event-1",
    type: "RosterUpdated",
    classSessionId: "session-1",
    reason: "CheckInRecorded",
    occurredAt: "2026-07-02T00:00:00.000Z",
    correlationId: "request-1",
    roster: {
      classSessionId: "session-1",
      state: "Open",
      counts: {
        present: 1,
        late: 0,
        pending: 2,
        absent: 0,
        excused: 0,
        manualPresent: 0,
        rejectedAttempts: 1,
      },
      rows: [
        {
          studentUserId: "student-1",
          studentCode: "S001",
          displayName: "Student One",
          attendanceStatus: "Present",
          checkInMethod: "QR",
          checkInAt: "2026-07-02T00:00:00.000Z",
          latestAttemptOutcome: "Success",
        },
      ],
    },
  };
}

describe("M09 realtime delivery gateway — FR-19 FR-14 AC-02 NFR-16", () => {
  it("publishes polling-compatible roster payloads to session subscribers", () => {
    const gateway = new RealtimeDeliveryGateway();
    const received: RealtimeRosterEvent[] = [];
    const unsubscribe = gateway.subscribeToRoster("session-1", (event) => received.push(event));

    const published = gateway.publishRosterUpdate({
      classSessionId: "session-1",
      reason: "CheckInRecorded",
      correlationId: "request-1",
      roster: rosterEvent().roster,
    });

    unsubscribe();
    expect(received).toEqual([published]);
    expect(published.type).toBe("RosterUpdated");
    expect(published.roster.counts.rejectedAttempts).toBe(1);
    expect(published.roster.rows[0]?.latestAttemptOutcome).toBe("Success");
  });

  it("serializes roster events as SSE frames without changing the roster contract", () => {
    const frame = formatServerSentEvent("roster.update", rosterEvent());

    expect(frame).toContain("event: roster.update\n");
    expect(frame).toContain("id: event-1\n");
    expect(frame).toContain('"classSessionId":"session-1"');
    expect(frame).toContain('"latestAttemptOutcome":"Success"');
  });

  it("retains bounded operational telemetry for QR and failure-distribution triage", () => {
    const gateway = new RealtimeDeliveryGateway();
    gateway.publishTelemetry({
      eventId: "telemetry-1",
      type: "QrTokenIssued",
      classSessionId: "session-1",
      tokenId: "token-1",
      issuedAt: "2026-07-02T00:00:00.000Z",
      expiresAt: "2026-07-02T00:00:30.000Z",
      ttlMs: 30_000,
      success: true,
      correlationId: "request-1",
    });
    gateway.publishTelemetry({
      eventId: "telemetry-2",
      type: "CheckInAttemptRecorded",
      classSessionId: "session-1",
      studentUserId: "student-1",
      outcome: "ExpiredQr",
      success: false,
      occurredAt: "2026-07-02T00:00:31.000Z",
      correlationId: "request-2",
    });

    expect(gateway.telemetrySnapshot({ classSessionId: "session-1" })).toHaveLength(2);
    expect(gateway.telemetrySnapshot({ type: "QrTokenIssued" })[0]?.type).toBe("QrTokenIssued");
  });
});
