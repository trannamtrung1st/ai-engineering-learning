import { ApiError } from "../../errors/api-error.js";
import {
  buildPaginatedResult,
  parsePagination,
  parseSort,
  type PaginatedResult,
} from "../../pagination/index.js";
import { findFeedbackByRegistrationId } from "../feedback/repository.js";
import { findEventById } from "../event/repository.js";
import {
  findRegistrationById,
  findRegistrationByParticipant,
} from "../registration/repository.js";
import {
  CERTIFICATE_ELIGIBILITY_STATES,
  type CertificateEligibilityState,
} from "@we-event/domain";
import {
  findEligibilityByRegistrationId,
  listEligibilitiesForEvent,
  listRegistrationsForEligibilityPaginated,
  persistEligibilityEvaluation,
  revokeEligibility,
} from "./repository.js";
import type {
  ActorContext,
  EligibilityListEntry,
  ListEligibilityQuery,
  RevokeEligibilityInput,
} from "./types.js";
import { toEligibilityResponse } from "./types.js";
import {
  assertRevokeAllowed,
  evaluateEligibilityRules,
} from "./validation.js";

const ELIGIBILITY_PARTICIPANT_STATES = ["Attended", "Absent"] as const;

export class EligibilityService {
  async getMyEligibility(
    eventId: string,
    participantId: string,
    context: ActorContext,
  ) {
    const event = await this.requireEvent(eventId);
    const registration = await findRegistrationByParticipant(
      eventId,
      participantId,
      [...ELIGIBILITY_PARTICIPANT_STATES],
    );

    if (!registration) {
      throw new ApiError({
        code: "NOT_FOUND",
        message: "No registration found for eligibility evaluation.",
        statusCode: 404,
        details: { eventId, participantId },
      });
    }

    const feedback = await findFeedbackByRegistrationId(registration.id);
    const evaluation = evaluateEligibilityRules(registration, event, feedback);
    const row = await persistEligibilityEvaluation(
      registration,
      evaluation,
      context,
    );

    return toEligibilityResponse(row);
  }

  async listEligibility(
    eventId: string,
    query: ListEligibilityQuery,
    context: ActorContext,
  ): Promise<PaginatedResult<EligibilityListEntry>> {
    const event = await this.requireEvent(eventId);

    const pagination = parsePagination(query, {
      defaultPageSize: 20,
      maxPageSize: 100,
    });

    let eligibilityFilter: CertificateEligibilityState | undefined;
    if (query.eligibility) {
      if (
        !CERTIFICATE_ELIGIBILITY_STATES.includes(
          query.eligibility as CertificateEligibilityState,
        )
      ) {
        throw new ApiError({
          code: "INVALID_INPUT",
          message: "Invalid eligibility filter.",
          statusCode: 400,
          details: { eligibility: query.eligibility },
        });
      }
      eligibilityFilter = query.eligibility as CertificateEligibilityState;
    }

    const sort = parseSort(
      query.sort,
      {
        participantId: "r.participant_id",
        updatedAt: "r.updated_at",
        evaluatedAt: "ce.evaluated_at",
      },
      "participantId",
    );

    const effectiveSort = query.sort?.trim()
      ? sort
      : { column: "r.participant_id", direction: "ASC" as const };

    const { items: registrations, total } =
      await listRegistrationsForEligibilityPaginated(eventId, {
        eligibility: eligibilityFilter,
        sortColumn: effectiveSort.column,
        sortDirection: effectiveSort.direction,
        limit: pagination.pageSize,
        offset: pagination.offset,
      });

    const existing = await listEligibilitiesForEvent(eventId);
    const byRegistration = new Map(
      existing.map((row) => [row.registrationId, row]),
    );

    const entries: EligibilityListEntry[] = [];

    for (const registration of registrations) {
      const feedback = await findFeedbackByRegistrationId(registration.id);
      const evaluation = evaluateEligibilityRules(
        registration,
        event,
        feedback,
      );

      const stored = byRegistration.get(registration.id);
      const needsRefresh =
        !stored ||
        stored.result === "PendingEvaluation" ||
        (stored.result !== "Revoked" && stored.result !== evaluation.result);

      const row = needsRefresh
        ? await persistEligibilityEvaluation(registration, evaluation, context)
        : stored;

      entries.push({
        registrationId: registration.id,
        participantId: registration.participantId,
        registrationState: registration.state,
        eligibility: toEligibilityResponse(row),
      });
    }

    return buildPaginatedResult(entries, total, pagination);
  }

  async revoke(
    eventId: string,
    registrationId: string,
    input: RevokeEligibilityInput,
    context: ActorContext,
  ) {
    const event = await this.requireEvent(eventId);

    const registration = await findRegistrationById(registrationId);
    if (!registration || registration.eventId !== eventId) {
      throw new ApiError({
        code: "NOT_FOUND",
        message: "Registration not found.",
        statusCode: 404,
        details: { registrationId, eventId },
      });
    }

    let existing = await findEligibilityByRegistrationId(registrationId);
    if (!existing) {
      const feedback = await findFeedbackByRegistrationId(registrationId);
      const evaluation = evaluateEligibilityRules(
        registration,
        event,
        feedback,
      );
      existing = await persistEligibilityEvaluation(
        registration,
        evaluation,
        context,
      );
    }

    assertRevokeAllowed(
      existing,
      context.actorRole,
      input.reasonCode,
      input.reasonText,
    );

    const row = await revokeEligibility(
      registration,
      input.reasonCode.trim(),
      input.reasonText.trim(),
      context,
    );

    return toEligibilityResponse(row);
  }

  private async requireEvent(eventId: string) {
    const event = await findEventById(eventId);
    if (!event) {
      throw new ApiError({
        code: "NOT_FOUND",
        message: "Event not found.",
        statusCode: 404,
        details: { eventId },
      });
    }
    return event;
  }
}

export const eligibilityService = new EligibilityService();
