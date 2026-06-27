import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import { VALIDATION_ERROR_CODES } from "@we-event/domain";

import {
  createDraftEvent,
  createRegistrationOpenEvent,
  registerParticipant,
  transitionEvent,
} from "../helpers/event-factory.js";
import {
  type E2EContext,
  type ErrorEnvelope,
  type PaginatedEnvelope,
  apiRequest,
  assertOk,
  createE2EContext,
  destroyE2EContext,
  futureWindow,
  newIdempotencyKey,
  ORGANIZER_ADMIN_SUB,
  parseJson,
  signDevToken,
} from "../helpers/setup.js";

describe("Check-in module — window validation, attendance, pagination (AC-05, AC-06, AC-07, AC-13, NFR-15, BR-17)", () => {
  let ctx: E2EContext;
  let organizerToken: string;

  before(async () => {
    ctx = await createE2EContext();
    organizerToken = await signDevToken(ctx.app, ORGANIZER_ADMIN_SUB, "OrganizerAdmin");
  });

  after(async () => {
    await destroyE2EContext(ctx);
  });

  it("AC-05 / TC-AC-05-004 / TC-AC-05-006: POST checkins returns HTTP 200 with checkinAt and attendance row", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
    });
    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const registered = await registerParticipant(ctx.app, participantToken, eventId);

    await transitionEvent(ctx.app, organizerToken, eventId, "close-registration");
    await transitionEvent(ctx.app, organizerToken, eventId, "start");

    const checkinResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/checkins`,
      token: organizerToken,
      payload: { registrationId: registered.registrationId },
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(checkinResponse.statusCode, checkinResponse.body, "staff check-in");
    const checkin = parseJson<{
      checkinAt: string;
      registrationState: string;
      method: string;
      participantId: string;
    }>(checkinResponse.body);
    assert.ok(checkin.checkinAt);
    assert.equal(checkin.registrationState, "CheckedIn");
    assert.equal(checkin.method, "Staff");
    assert.ok(checkin.participantId);

    const attendanceResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/attendance?page=1&pageSize=20`,
      token: organizerToken,
    });
    assertOk(attendanceResponse.statusCode, attendanceResponse.body, "attendance list");
    const attendance = parseJson<
      PaginatedEnvelope<{ registrationId: string; checkinAt: string | null }>
    >(attendanceResponse.body);
    const row = attendance.items.find(
      (item) => item.registrationId === registered.registrationId,
    );
    assert.ok(row);
    assert.equal(row.checkinAt, checkin.checkinAt);
  });

  it("FR-14 / TC-FR-14-021: dev participant sub resolves for self check-in HTTP path", async () => {
    const devSub = "participant-checkin-e2e-dev-1";
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
      selfCheckinEnabled: true,
    });
    const participantToken = await signDevToken(ctx.app, devSub, "Participant");
    await registerParticipant(ctx.app, participantToken, eventId);

    await transitionEvent(ctx.app, organizerToken, eventId, "close-registration");
    await transitionEvent(ctx.app, organizerToken, eventId, "start");

    const checkinResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/self-checkin`,
      token: participantToken,
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(checkinResponse.statusCode, checkinResponse.body, "dev sub self check-in");
    const checkin = parseJson<{
      checkinAt: string;
      registrationState: string;
      method: string;
    }>(checkinResponse.body);
    assert.ok(checkin.checkinAt);
    assert.equal(checkin.registrationState, "CheckedIn");
    assert.equal(checkin.method, "Self");
  });

  it("AC-05 / FR-14 / TC-AC-05-005: POST self-checkin returns HTTP 200 with CheckedIn state", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
    });
    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    await registerParticipant(ctx.app, participantToken, eventId);

    await transitionEvent(ctx.app, organizerToken, eventId, "close-registration");
    await transitionEvent(ctx.app, organizerToken, eventId, "start");

    const checkinResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/self-checkin`,
      token: participantToken,
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(checkinResponse.statusCode, checkinResponse.body, "self check-in");
    const checkin = parseJson<{
      checkinAt: string;
      registrationState: string;
      method: string;
    }>(checkinResponse.body);
    assert.ok(checkin.checkinAt);
    assert.equal(checkin.registrationState, "CheckedIn");
    assert.equal(checkin.method, "Self");

    const statusResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/registration-status`,
      token: participantToken,
    });
    assertOk(statusResponse.statusCode, statusResponse.body, "registration status");
    const status = parseJson<{ registration: { state: string } }>(statusResponse.body);
    assert.equal(status.registration.state, "CheckedIn");
  });

  it("AC-06 / TC-AC-06-005: out-of-window staff check-in returns CHECKIN_WINDOW_CLOSED", async () => {
    const future = futureWindow(86_400_000);

    const { eventId } = await createDraftEvent(ctx.app, organizerToken, {
      capacity: 5,
      checkinOpenAt: future.open,
      checkinCloseAt: future.close,
    });
    await transitionEvent(ctx.app, organizerToken, eventId, "publish");
    await transitionEvent(ctx.app, organizerToken, eventId, "open-registration");

    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const registered = await registerParticipant(ctx.app, participantToken, eventId);

    await transitionEvent(ctx.app, organizerToken, eventId, "close-registration");
    await transitionEvent(ctx.app, organizerToken, eventId, "start");

    const checkinResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/checkins`,
      token: organizerToken,
      payload: { registrationId: registered.registrationId },
      idempotencyKey: newIdempotencyKey(),
    });
    assert.equal(checkinResponse.statusCode, 422, checkinResponse.body);
    const error = parseJson<ErrorEnvelope>(checkinResponse.body);
    assert.equal(error.error.code, VALIDATION_ERROR_CODES.CHECKIN_WINDOW_CLOSED);
  });

  it("AC-06 / TC-AC-06-016: concurrent out-of-window check-in requests all fail without records", async () => {
    const future = futureWindow(86_400_000);

    const { eventId } = await createDraftEvent(ctx.app, organizerToken, {
      capacity: 5,
      checkinOpenAt: future.open,
      checkinCloseAt: future.close,
    });
    await transitionEvent(ctx.app, organizerToken, eventId, "publish");
    await transitionEvent(ctx.app, organizerToken, eventId, "open-registration");

    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const registered = await registerParticipant(ctx.app, participantToken, eventId);

    await transitionEvent(ctx.app, organizerToken, eventId, "close-registration");
    await transitionEvent(ctx.app, organizerToken, eventId, "start");

    const responses = await Promise.all(
      Array.from({ length: 3 }, () =>
        apiRequest(ctx.app, {
          method: "POST",
          path: `/events/${eventId}/checkins`,
          token: organizerToken,
          payload: { registrationId: registered.registrationId },
          idempotencyKey: newIdempotencyKey(),
        }),
      ),
    );

    for (const response of responses) {
      assert.equal(response.statusCode, 422, response.body);
      const error = parseJson<ErrorEnvelope>(response.body);
      assert.equal(error.error.code, VALIDATION_ERROR_CODES.CHECKIN_WINDOW_CLOSED);
    }

    const attendanceResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/attendance?page=1&pageSize=20`,
      token: organizerToken,
    });
    assertOk(attendanceResponse.statusCode, attendanceResponse.body, "attendance list");
    const attendance = parseJson<
      PaginatedEnvelope<{ registrationId: string; checkinAt: string | null }>
    >(attendanceResponse.body);
    const row = attendance.items.find(
      (item) => item.registrationId === registered.registrationId,
    );
    assert.ok(row, "registration appears in attendance list");
    assert.equal(row.checkinAt, null, "no check-in record created");
  });

  it("AC-06 / NFR-13 / NFR-15 / TC-AC-06-018: out-of-window error includes requestId and window bounds", async () => {
    const future = futureWindow(86_400_000);

    const { eventId } = await createDraftEvent(ctx.app, organizerToken, {
      capacity: 5,
      checkinOpenAt: future.open,
      checkinCloseAt: future.close,
    });
    await transitionEvent(ctx.app, organizerToken, eventId, "publish");
    await transitionEvent(ctx.app, organizerToken, eventId, "open-registration");

    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const registered = await registerParticipant(ctx.app, participantToken, eventId);

    await transitionEvent(ctx.app, organizerToken, eventId, "close-registration");
    await transitionEvent(ctx.app, organizerToken, eventId, "start");

    const checkinResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/checkins`,
      token: organizerToken,
      payload: { registrationId: registered.registrationId },
      idempotencyKey: newIdempotencyKey(),
    });
    assert.equal(checkinResponse.statusCode, 422, checkinResponse.body);
    const error = parseJson<
      ErrorEnvelope & {
        error: {
          requestId: string;
          details: { checkinOpenAt?: string; checkinCloseAt?: string };
        };
      }
    >(checkinResponse.body);
    assert.equal(error.error.code, VALIDATION_ERROR_CODES.CHECKIN_WINDOW_CLOSED);
    assert.match(error.error.requestId, /^[0-9a-f-]{36}$/i, "NFR-15 requestId");
    assert.ok(error.error.details?.checkinOpenAt, "window bounds in details");
    assert.ok(error.error.details?.checkinCloseAt, "window bounds in details");
  });

  it("AC-07 / TC-AC-07-017: POST complete rejected when event not in InProgress", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
    });

    const completeResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/complete`,
      token: organizerToken,
      idempotencyKey: newIdempotencyKey(),
    });
    assert.equal(completeResponse.statusCode, 409, completeResponse.body);
    const error = parseJson<ErrorEnvelope>(completeResponse.body);
    assert.equal(error.error.code, "INVALID_STATE_TRANSITION");

    const statusResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}`,
      token: organizerToken,
    });
    assertOk(statusResponse.statusCode, statusResponse.body, "event status");
    const event = parseJson<{ state: string }>(statusResponse.body);
    assert.equal(event.state, "RegistrationOpen");
  });

  it("AC-07 / BR-17 / TC-AC-07-020: Attended registration satisfies attendance eligibility rule", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
      feedbackRequired: true,
    });
    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const registered = await registerParticipant(ctx.app, participantToken, eventId);

    await transitionEvent(ctx.app, organizerToken, eventId, "close-registration");
    await transitionEvent(ctx.app, organizerToken, eventId, "start");

    await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/checkins`,
      token: organizerToken,
      payload: { registrationId: registered.registrationId },
      idempotencyKey: newIdempotencyKey(),
    });

    await transitionEvent(ctx.app, organizerToken, eventId, "complete");

    const eligibilityResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/eligibility/me`,
      token: participantToken,
    });
    assertOk(eligibilityResponse.statusCode, eligibilityResponse.body, "BR-17 eligibility");
    const eligibility = parseJson<{
      result: string;
      reasonCode: string;
      reasonText: string;
    }>(eligibilityResponse.body);

    assert.notEqual(
      eligibility.reasonCode,
      VALIDATION_ERROR_CODES.NOT_ELIGIBLE_ATTENDANCE,
      "Attended participant must pass BR-17 attendance rule",
    );
    assert.equal(eligibility.result, "NotEligible");
    assert.equal(
      eligibility.reasonCode,
      VALIDATION_ERROR_CODES.NOT_ELIGIBLE_FEEDBACK,
    );
    assert.ok(eligibility.reasonText);
  });

  it("AC-07 / TC-AC-07-019: GET attendance reflects Attended participants after completion", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
    });
    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const registered = await registerParticipant(ctx.app, participantToken, eventId);

    await transitionEvent(ctx.app, organizerToken, eventId, "close-registration");
    await transitionEvent(ctx.app, organizerToken, eventId, "start");

    const checkinResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/checkins`,
      token: organizerToken,
      payload: { registrationId: registered.registrationId },
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(checkinResponse.statusCode, checkinResponse.body, "staff check-in");
    const checkin = parseJson<{ checkinAt: string }>(checkinResponse.body);
    assert.ok(checkin.checkinAt);

    await transitionEvent(ctx.app, organizerToken, eventId, "complete");

    const attendanceResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/attendance?page=1&pageSize=20`,
      token: organizerToken,
    });
    assertOk(attendanceResponse.statusCode, attendanceResponse.body, "attendance list");
    const attendance = parseJson<
      PaginatedEnvelope<{ registrationId: string; checkinAt: string | null }>
    >(attendanceResponse.body);
    const row = attendance.items.find(
      (item) => item.registrationId === registered.registrationId,
    );
    assert.ok(row);
    assert.equal(row.checkinAt, checkin.checkinAt);

    const registrationsResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/registrations?state=Attended&page=1&pageSize=20`,
      token: organizerToken,
    });
    assertOk(registrationsResponse.statusCode, registrationsResponse.body, "attended list");
    const registrations = parseJson<
      PaginatedEnvelope<{ registrationId: string; state: string }>
    >(registrationsResponse.body);
    const attended = registrations.items.find(
      (item) => item.registrationId === registered.registrationId,
    );
    assert.ok(attended);
    assert.equal(attended.state, "Attended");
  });

  it("TC-AC-05-013 / AC-05 / BR-11 / NFR-02: concurrent duplicate check-in yields at most one record", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
    });
    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const registered = await registerParticipant(ctx.app, participantToken, eventId);

    await transitionEvent(ctx.app, organizerToken, eventId, "close-registration");
    await transitionEvent(ctx.app, organizerToken, eventId, "start");

    const responses = await Promise.all(
      Array.from({ length: 3 }, () =>
        apiRequest(ctx.app, {
          method: "POST",
          path: `/events/${eventId}/checkins`,
          token: organizerToken,
          payload: { registrationId: registered.registrationId },
          idempotencyKey: newIdempotencyKey(),
        }),
      ),
    );

    const success = responses.filter((response) => response.statusCode === 200);
    const conflicts = responses.filter((response) => response.statusCode === 409);
    assert.equal(success.length, 1, "exactly one concurrent check-in succeeds");
    assert.equal(conflicts.length, 2, "duplicate requests conflict");

    for (const response of conflicts) {
      const error = parseJson<ErrorEnvelope>(response.body);
      assert.equal(error.error.code, VALIDATION_ERROR_CODES.CHECKIN_ALREADY_RECORDED);
    }

    const checkin = parseJson<{ checkinAt: string; registrationState: string }>(
      success[0]!.body,
    );
    assert.ok(checkin.checkinAt);
    assert.equal(checkin.registrationState, "CheckedIn");

    const attendanceResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/attendance?page=1&pageSize=20`,
      token: organizerToken,
    });
    assertOk(attendanceResponse.statusCode, attendanceResponse.body, "attendance list");
    const attendance = parseJson<
      PaginatedEnvelope<{ registrationId: string; checkinAt: string | null }>
    >(attendanceResponse.body);
    const rowsWithCheckin = attendance.items.filter(
      (item) =>
        item.registrationId === registered.registrationId && item.checkinAt !== null,
    );
    assert.equal(rowsWithCheckin.length, 1, "single check-in record in attendance list");
  });

  it("TC-AC-05-009 / AC-05 / FR-13: participant denied staff check-in endpoint", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
    });
    const participantAToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const participantBToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const registeredB = await registerParticipant(ctx.app, participantBToken, eventId);

    await transitionEvent(ctx.app, organizerToken, eventId, "close-registration");
    await transitionEvent(ctx.app, organizerToken, eventId, "start");

    const checkinResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/checkins`,
      token: participantAToken,
      payload: { registrationId: registeredB.registrationId },
      idempotencyKey: newIdempotencyKey(),
    });
    assert.equal(checkinResponse.statusCode, 403, checkinResponse.body);
    const error = parseJson<ErrorEnvelope>(checkinResponse.body);
    assert.equal(error.error.code, "FORBIDDEN");

    const attendanceResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/attendance?page=1&pageSize=20`,
      token: organizerToken,
    });
    assertOk(attendanceResponse.statusCode, attendanceResponse.body, "attendance list");
    const attendance = parseJson<
      PaginatedEnvelope<{ registrationId: string; checkinAt: string | null }>
    >(attendanceResponse.body);
    const row = attendance.items.find(
      (item) => item.registrationId === registeredB.registrationId,
    );
    assert.ok(row);
    assert.equal(row.checkinAt, null, "no check-in record created for participant B");
  });

  it("TC-AC-05-010 / AC-05: OrganizerStaff denied check-in on event outside assigned scope", async () => {
    const assignedEventId = (
      await createRegistrationOpenEvent(ctx.app, organizerToken, { capacity: 5 })
    ).eventId;
    const unassignedEventId = (
      await createRegistrationOpenEvent(ctx.app, organizerToken, { capacity: 5 })
    ).eventId;
    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const registered = await registerParticipant(
      ctx.app,
      participantToken,
      unassignedEventId,
    );

    await transitionEvent(ctx.app, organizerToken, unassignedEventId, "close-registration");
    await transitionEvent(ctx.app, organizerToken, unassignedEventId, "start");

    const staffSub = randomUUID();
    const staffToken = await signDevToken(ctx.app, staffSub, "OrganizerStaff", [
      assignedEventId,
    ]);

    const checkinResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${unassignedEventId}/checkins`,
      token: staffToken,
      payload: { registrationId: registered.registrationId },
      idempotencyKey: newIdempotencyKey(),
    });
    assert.equal(checkinResponse.statusCode, 403, checkinResponse.body);
    const error = parseJson<ErrorEnvelope>(checkinResponse.body);
    assert.equal(error.error.code, "FORBIDDEN");
  });

  it("AC-13 / TC-AC-13-012: paginated attendance list returns envelope metadata and empty page beyond totalPages", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 10,
    });
    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const registered = await registerParticipant(ctx.app, participantToken, eventId);

    await transitionEvent(ctx.app, organizerToken, eventId, "close-registration");
    await transitionEvent(ctx.app, organizerToken, eventId, "start");

    await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/checkins`,
      token: organizerToken,
      payload: { registrationId: registered.registrationId },
      idempotencyKey: newIdempotencyKey(),
    });

    const pageResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/attendance?page=1&pageSize=1`,
      token: organizerToken,
    });
    assertOk(pageResponse.statusCode, pageResponse.body, "attendance page 1");
    const page = parseJson<PaginatedEnvelope<unknown>>(pageResponse.body);
    assert.equal(page.page, 1);
    assert.equal(page.pageSize, 1);
    assert.equal(page.total, 1);
    assert.equal(page.totalPages, 1);
    assert.equal(page.items.length, 1);

    const beyondResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/attendance?page=99&pageSize=1`,
      token: organizerToken,
    });
    assertOk(beyondResponse.statusCode, beyondResponse.body, "attendance beyond pages");
    const beyond = parseJson<PaginatedEnvelope<unknown>>(beyondResponse.body);
    assert.deepEqual(beyond.items, []);
    assert.equal(beyond.total, 1);
    assert.equal(beyond.totalPages, 1);
  });
});
