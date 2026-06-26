import { REGISTRATION_STATES, type RegistrationState } from "@we-event/domain";
import { resolveActorId } from "../../auth/resolve-actor-id.js";
import { ApiError } from "../../errors/api-error.js";
import {
  buildPaginatedResult,
  parsePagination,
  parseSort,
  type PaginatedResult,
} from "../../pagination/index.js";
import { findEventById } from "../event/repository.js";
import { ensureParticipantAccount } from "../user/repository.js";
import {
  cancelRegistration,
  createRegistration,
  findActiveRegistration,
  findLatestParticipantRegistration,
  findRegistrationById,
  listRegistrationsForEvent,
  listRegistrationsForParticipant,
  listWaitlistForEvent,
  loadRegistrationWithWaitlist,
} from "./repository.js";
import type {
  ActorContext,
  CancelInput,
  ListMyRegistrationsQuery,
  ListRegistrationsQuery,
  ListWaitlistQuery,
  MyRegistrationListItem,
  WaitlistListItem,
} from "./types.js";
import {
  assertNoDuplicateActive,
  assertOrganizerCancellationAllowed,
  assertParticipantCancellationAllowed,
  assertRegistrationWindowOpen,
  toRegistrationResponse,
} from "./validation.js";

export class RegistrationService {
  async register(
    eventId: string,
    participantId: string,
    context: ActorContext,
  ) {
    const resolvedParticipantId = resolveActorId(participantId);
    const event = await this.requireEvent(eventId);
    assertRegistrationWindowOpen(event);

    await ensureParticipantAccount(resolvedParticipantId);

    const existing = await findActiveRegistration(eventId, resolvedParticipantId);
    assertNoDuplicateActive(existing);

    const registration = await createRegistration(
      eventId,
      resolvedParticipantId,
      {
        actorId: resolvedParticipantId,
        actorRole: context.actorRole,
      },
    );

    return toRegistrationResponse(registration, registration.waitlistPosition);
  }

  async getStatus(eventId: string, participantId: string) {
    const resolvedParticipantId = resolveActorId(participantId);
    const registration = await findLatestParticipantRegistration(
      eventId,
      resolvedParticipantId,
    );
    if (!registration) {
      return { registration: null };
    }
    const withWaitlist = await loadRegistrationWithWaitlist(registration);
    return {
      registration: toRegistrationResponse(
        withWaitlist,
        withWaitlist.waitlistPosition,
      ),
    };
  }

  async cancel(
    eventId: string,
    registrationId: string,
    context: ActorContext,
    input: CancelInput = {},
    options: { asOrganizer?: boolean } = {},
  ) {
    const registration = await this.requireRegistration(registrationId, eventId);
    const event = await this.requireEvent(eventId);

    if (options.asOrganizer) {
      assertOrganizerCancellationAllowed(registration);
    } else {
      if (resolveActorId(registration.participantId) !== resolveActorId(context.actorId)) {
        throw new ApiError({
          code: "FORBIDDEN",
          message: "You can only cancel your own registration.",
          statusCode: 403,
          details: { registrationId },
        });
      }
      assertParticipantCancellationAllowed(event, registration);
    }

    const cancelledState = options.asOrganizer
      ? "CancelledByOrganizer"
      : "CancelledByUser";

    const result = await cancelRegistration(registration, cancelledState, {
      ...context,
      reasonCode: input.reasonCode,
      reasonText: input.reasonText,
    });

    const cancelled = await loadRegistrationWithWaitlist(result.cancelled);

    return {
      cancelled: toRegistrationResponse(
        cancelled,
        cancelled.waitlistPosition,
      ),
      promoted: result.promoted
        ? toRegistrationResponse(result.promoted, null)
        : null,
    };
  }

  async listRegistrations(
    eventId: string,
    query: ListRegistrationsQuery = {},
  ): Promise<
    PaginatedResult<ReturnType<typeof toRegistrationResponse>>
  > {
    await this.requireEvent(eventId);

    const pagination = parsePagination(query, {
      defaultPageSize: 20,
      maxPageSize: 100,
    });

    const sort = parseSort(
      query.sort,
      {
        updatedAt: "r.updated_at",
        requestedAt: "r.requested_at",
      },
      "updatedAt",
    );

    let stateFilter: RegistrationState | undefined;
    if (query.state) {
      if (!REGISTRATION_STATES.includes(query.state as RegistrationState)) {
        throw new ApiError({
          code: "INVALID_INPUT",
          message: "Invalid registration state filter.",
          statusCode: 400,
          details: { state: query.state },
        });
      }
      stateFilter = query.state as RegistrationState;
    }

    const effectiveSort = query.sort?.trim()
      ? sort
      : { column: "r.updated_at", direction: "DESC" as const };

    const { items, total } = await listRegistrationsForEvent(eventId, {
      state: stateFilter,
      sortColumn: effectiveSort.column,
      sortDirection: effectiveSort.direction,
      limit: pagination.pageSize,
      offset: pagination.offset,
    });

    return buildPaginatedResult(
      items.map((row) => toRegistrationResponse(row, row.waitlistPosition)),
      total,
      pagination,
    );
  }

  async listWaitlist(
    eventId: string,
    query: ListWaitlistQuery = {},
  ): Promise<PaginatedResult<WaitlistListItem>> {
    await this.requireEvent(eventId);

    const pagination = parsePagination(query, {
      defaultPageSize: 20,
      maxPageSize: 100,
    });

    const sort = parseSort(
      query.sort,
      {
        position: "w.position",
        enqueuedAt: "w.enqueued_at",
      },
      "position",
    );

    const { items, total } = await listWaitlistForEvent(eventId, {
      sortColumn: sort.column,
      sortDirection: sort.direction,
      limit: pagination.pageSize,
      offset: pagination.offset,
    });

    return buildPaginatedResult(items, total, pagination);
  }

  async listMyRegistrations(
    participantId: string,
    query: ListMyRegistrationsQuery = {},
  ): Promise<PaginatedResult<MyRegistrationListItem>> {
    const resolvedParticipantId = resolveActorId(participantId);
    const pagination = parsePagination(query, {
      defaultPageSize: 20,
      maxPageSize: 100,
    });

    const sort = parseSort(
      query.sort,
      {
        updatedAt: "r.updated_at",
        requestedAt: "r.requested_at",
      },
      "updatedAt",
    );

    let stateFilter: RegistrationState | undefined;
    if (query.state) {
      if (!REGISTRATION_STATES.includes(query.state as RegistrationState)) {
        throw new ApiError({
          code: "INVALID_INPUT",
          message: "Invalid registration state filter.",
          statusCode: 400,
          details: { state: query.state },
        });
      }
      stateFilter = query.state as RegistrationState;
    }

    const effectiveSort = query.sort?.trim()
      ? sort
      : { column: "r.updated_at", direction: "DESC" as const };

    const { items, total } = await listRegistrationsForParticipant(
      resolvedParticipantId,
      {
        state: stateFilter,
        sortColumn: effectiveSort.column,
        sortDirection: effectiveSort.direction,
        limit: pagination.pageSize,
        offset: pagination.offset,
      },
    );

    return buildPaginatedResult(items, total, pagination);
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

  private async requireRegistration(registrationId: string, eventId: string) {
    const registration = await findRegistrationById(registrationId);
    if (!registration || registration.eventId !== eventId) {
      throw new ApiError({
        code: "NOT_FOUND",
        message: "Registration not found.",
        statusCode: 404,
        details: { registrationId, eventId },
      });
    }
    return registration;
  }
}

export const registrationService = new RegistrationService();
