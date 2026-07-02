import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { ErrorCode } from "@attendly/domain";
import {
  combineGuards,
  createAuthenticate,
  createAuthorizeGuard,
  type IdentityServices,
} from "../identity/middleware.js";
import { forbidden, resolveRequestId, sendApiError, sendApiSuccess } from "../identity/http.js";
import type { ApiErrorEnvelope } from "@attendly/domain";
import { buildPaginationMeta, parsePagination } from "../academic-structure/pagination.js";
import type { SessionLifecycleRepository } from "./repository.js";
import type { SessionState } from "./types.js";

const INVALID_TRANSITION_MESSAGE =
  "Không thể thực hiện thao tác cho trạng thái hiện tại.";

function paramsSessionId(request: FastifyRequest) {
  const params = request.params as { sessionId?: string };
  return { classSessionId: params.sessionId };
}

function idempotencyKey(request: FastifyRequest): string | undefined {
  const header = request.headers["idempotency-key"];
  return typeof header === "string" && header.length > 0 ? header : undefined;
}

function sendInvalidTransition(
  reply: FastifyReply,
  request: FastifyRequest,
  fromState: string,
): void {
  const body: ApiErrorEnvelope = {
    data: null,
    meta: {
      requestId: resolveRequestId(request),
      timestamp: new Date().toISOString(),
    },
    error: {
      code: ErrorCode.InvalidSessionTransition,
      message: INVALID_TRANSITION_MESSAGE,
      details: { fromState },
    },
  };
  void reply.status(409).send(body);
}

function isStaffSessionReader(roles: string[]): boolean {
  return roles.some((role) =>
    ["Lecturer", "DepartmentAdmin", "AcademicAdmin"].includes(role),
  );
}

async function resolveAuthorizedSectionIds(
  services: IdentityServices,
  actorUserId: string,
  roles: string[],
): Promise<string[] | null> {
  const isBroadReader = roles.some((role) =>
    ["DepartmentAdmin", "AcademicAdmin"].includes(role),
  );
  if (isBroadReader) {
    return null;
  }
  return services.repository.getLecturerClassSectionIds(actorUserId);
}

function canAccessSection(
  sectionId: string,
  scopedSectionIds: string[] | null,
): boolean {
  if (scopedSectionIds === null) {
    return true;
  }
  return scopedSectionIds.includes(sectionId);
}

export async function registerSessionLifecycleRoutes(
  app: FastifyInstance,
  services: IdentityServices,
  repository: SessionLifecycleRepository,
): Promise<void> {
  const authenticate = createAuthenticate(services);

  const guardSessionControl = createAuthorizeGuard(services, {
    resource: "SessionControl",
    action: "execute",
    resolveScope: paramsSessionId,
  });

  app.get("/class-sessions", { preHandler: authenticate }, async (request, reply) => {
    const actor = request.actor!;
    if (!isStaffSessionReader(actor.roles)) {
      forbidden(reply, request);
      return;
    }

    const query = request.query as {
      page?: string;
      pageSize?: string;
      classSectionId?: string;
      state?: string;
      search?: string;
      from?: string;
      to?: string;
      sortBy?: string;
      sortOrder?: string;
    };

    const scopedSectionIds = await resolveAuthorizedSectionIds(
      services,
      actor.userId,
      actor.roles,
    );

    let effectiveSectionIds = scopedSectionIds ?? [];
    if (scopedSectionIds === null) {
      effectiveSectionIds = query.classSectionId ? [query.classSectionId] : [];
    } else if (query.classSectionId) {
      if (!canAccessSection(query.classSectionId, scopedSectionIds)) {
        forbidden(reply, request);
        return;
      }
      effectiveSectionIds = [query.classSectionId];
    }

    const { page, pageSize, offset } = parsePagination(query);
    const sortBy = query.sortBy === "state" ? "state" : "startTime";
    const sortOrder = query.sortOrder === "asc" ? "asc" : "desc";
    const stateFilter = query.state as SessionState | undefined;
    const validStates: SessionState[] = ["Scheduled", "Open", "Closed", "Cancelled"];
    const state =
      stateFilter && validStates.includes(stateFilter) ? stateFilter : undefined;

    const { items, total } = await repository.listClassSessions({
      classSectionIds: effectiveSectionIds,
      state,
      search: query.search,
      from: query.from,
      to: query.to,
      sortBy,
      sortOrder,
      offset,
      limit: pageSize,
    });

    void reply.status(200).send({
      data: items,
      meta: {
        requestId: resolveRequestId(request),
        timestamp: new Date().toISOString(),
        pagination: buildPaginationMeta(page, pageSize, total),
      },
      error: null,
    });
  });

  app.get(
    "/class-sessions/:sessionId",
    { preHandler: combineGuards(authenticate, guardSessionControl) },
    async (request, reply) => {
      const params = request.params as { sessionId: string };
      const session = await repository.getClassSessionById(params.sessionId);
      if (!session) {
        sendApiError(reply, request, 404, ErrorCode.SessionNotFound);
        return;
      }
      sendApiSuccess(reply, request, 200, session);
    },
  );

  app.post(
    "/class-sessions/:sessionId/open",
    { preHandler: combineGuards(authenticate, guardSessionControl) },
    async (request, reply) => {
      const params = request.params as { sessionId: string };
      const body = (request.body ?? {}) as { roomId?: string };
      const actor = request.actor!;

      const outcome = await repository.openSession(params.sessionId, actor.userId, {
        roomId: body.roomId,
        idempotencyKey: idempotencyKey(request),
        correlationId: resolveRequestId(request),
      });

      if (!outcome.ok) {
        if (outcome.error.code === "SessionNotFound") {
          sendApiError(reply, request, 404, ErrorCode.SessionNotFound);
          return;
        }
        if (outcome.error.code === "InvalidSessionTransition") {
          sendInvalidTransition(reply, request, outcome.error.fromState);
          return;
        }
        sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
        return;
      }

      sendApiSuccess(reply, request, 200, outcome.result);
    },
  );

  app.post(
    "/class-sessions/:sessionId/close",
    { preHandler: combineGuards(authenticate, guardSessionControl) },
    async (request, reply) => {
      const params = request.params as { sessionId: string };
      const actor = request.actor!;

      const outcome = await repository.closeSession(params.sessionId, actor.userId, {
        idempotencyKey: idempotencyKey(request),
        correlationId: resolveRequestId(request),
      });

      if (!outcome.ok) {
        if (outcome.error.code === "SessionNotFound") {
          sendApiError(reply, request, 404, ErrorCode.SessionNotFound);
          return;
        }
        if (outcome.error.code === "InvalidSessionTransition") {
          sendInvalidTransition(reply, request, outcome.error.fromState);
          return;
        }
        sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
        return;
      }

      sendApiSuccess(reply, request, 200, outcome.result);
    },
  );
}
