import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { ErrorCode } from "@attendly/domain";
import {
  combineGuards,
  createAuthenticate,
  createAuthorizeGuard,
  type IdentityServices,
} from "../identity/middleware.js";
import {
  forbidden,
  resolveRequestId,
  sendApiError,
  sendApiSuccess,
} from "../identity/http.js";
import { buildPaginationMeta, parsePagination } from "../academic-structure/pagination.js";
import type { PolicyEngineRepository } from "./repository.js";
import {
  buildFieldOverridesFromBody,
  isPolicyScopeType,
  mapCreateBodyToInput,
  mergeFieldOverrides,
  validatePolicyCreateInput,
  validatePolicyUpdateInput,
} from "./validation.js";
import type { PolicyScopeType } from "./types.js";

function requireAcademicAdmin(
  actor: FastifyRequest["actor"],
  reply: FastifyReply,
  request: FastifyRequest,
): boolean {
  if (!actor?.roles.includes("AcademicAdmin")) {
    forbidden(reply, request);
    return false;
  }
  return true;
}

function paginatedPolicies(
  reply: FastifyReply,
  request: FastifyRequest,
  items: unknown[],
  page: number,
  pageSize: number,
  totalItems: number,
): void {
  void reply.status(200).send({
    data: items,
    meta: {
      requestId: resolveRequestId(request),
      timestamp: new Date().toISOString(),
      pagination: buildPaginationMeta(page, pageSize, totalItems),
    },
    error: null,
  });
}

export async function registerPolicyRoutes(
  app: FastifyInstance,
  services: IdentityServices,
  repository: PolicyEngineRepository,
): Promise<void> {
  const authenticate = createAuthenticate(services);

  const guardPolicyRead = createAuthorizeGuard(services, {
    resource: "AttendancePolicy",
    action: "read",
    resolveScope: (request) => {
      const query = request.query as { classSectionId?: string };
      return { classSectionId: query.classSectionId };
    },
  });

  const guardPolicyUpdate = createAuthorizeGuard(services, {
    resource: "AttendancePolicy",
    action: "update",
  });

  app.get(
    "/policies/effective",
    { preHandler: combineGuards(authenticate, guardPolicyRead) },
    async (request, reply) => {
      const query = request.query as { classSectionId?: string };
      if (!query.classSectionId) {
        sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
        return;
      }

      const resolved = await repository.resolveEffectivePolicy(query.classSectionId);
      if (!resolved) {
        sendApiError(reply, request, 404, ErrorCode.InvalidPayload);
        return;
      }

      sendApiSuccess(reply, request, 200, repository.toResolvedApi(resolved));
    },
  );

  app.get("/policies", { preHandler: authenticate }, async (request, reply) => {
    if (!requireAcademicAdmin(request.actor, reply, request)) return;

    const query = request.query as { page?: string; pageSize?: string; scopeLevel?: string };
    const { page, pageSize } = parsePagination(query);
    const scopeType =
      query.scopeLevel && isPolicyScopeType(query.scopeLevel)
        ? (query.scopeLevel as PolicyScopeType)
        : undefined;

    const { items, totalItems } = await repository.listPolicies({ page, pageSize, scopeType });
    paginatedPolicies(
      reply,
      request,
      items.map((item) => repository.toApiPolicy(item)),
      page,
      pageSize,
      totalItems,
    );
  });

  app.get("/policies/:policyId", { preHandler: authenticate }, async (request, reply) => {
    if (!requireAcademicAdmin(request.actor, reply, request)) return;

    const { policyId } = request.params as { policyId: string };
    const policy = await repository.getPolicyById(policyId);
    if (!policy) {
      sendApiError(reply, request, 404, ErrorCode.InvalidPayload);
      return;
    }

    sendApiSuccess(reply, request, 200, repository.toApiPolicy(policy));
  });

  app.post(
    "/policies",
    { preHandler: combineGuards(authenticate, guardPolicyUpdate) },
    async (request, reply) => {
      const body = request.body as Record<string, unknown>;
      const validationError = validatePolicyCreateInput(body);
      if (validationError) {
        sendApiError(reply, request, 400, validationError.code);
        return;
      }

      const input = mapCreateBodyToInput(body);
      const policy = await repository.createPolicy(input);

      if (request.actor) {
        await repository.writePolicyAudit({
          actorUserId: request.actor.userId,
          policyId: policy.id,
          oldValue: null,
          newValue: repository.toApiPolicy(policy) as unknown as Record<string, unknown>,
          correlationId: request.headers["idempotency-key"] as string | undefined,
        });
      }

      sendApiSuccess(reply, request, 200, repository.toApiPolicy(policy));
    },
  );

  app.patch(
    "/policies/:policyId",
    { preHandler: combineGuards(authenticate, guardPolicyUpdate) },
    async (request, reply) => {
      const { policyId } = request.params as { policyId: string };
      const existing = await repository.getPolicyById(policyId);
      if (!existing) {
        sendApiError(reply, request, 404, ErrorCode.InvalidPayload);
        return;
      }

      const body = request.body as Record<string, unknown>;
      const currentValues = repository.recordToEffectiveValues(existing);
      const patchError = validatePolicyUpdateInput(body, currentValues);
      if (patchError) {
        sendApiError(reply, request, 400, patchError.code);
        return;
      }

      const fieldOverrides = mergeFieldOverrides(
        existing.fieldOverrides,
        buildFieldOverridesFromBody(body),
      );

      const gpsRequired =
        body.gpsRequired !== undefined ? body.gpsRequired === true : existing.gpsRequired;

      const updated = await repository.updatePolicy(
        policyId,
        {
          checkInOpeningOffsetMinutes:
            body.checkInOpeningOffsetMinutes !== undefined
              ? body.checkInOpeningOffsetMinutes === null
                ? null
                : Number(body.checkInOpeningOffsetMinutes)
              : undefined,
          presentWindowMinutes:
            body.presentWindowMinutes !== undefined
              ? Number(body.presentWindowMinutes)
              : undefined,
          lateWindowMinutes:
            body.lateWindowMinutes !== undefined ? Number(body.lateWindowMinutes) : undefined,
          autoCloseEnabled:
            body.autoCloseEnabled !== undefined ? body.autoCloseEnabled === true : undefined,
          absenceThresholdPercent:
            body.absenceThresholdPercent !== undefined
              ? body.absenceThresholdPercent === null
                ? null
                : Number(body.absenceThresholdPercent)
              : undefined,
          excusedCountsTowardThreshold:
            body.excusedCountsTowardThreshold !== undefined
              ? body.excusedCountsTowardThreshold === true
              : undefined,
          manualEditWindowHours:
            body.manualEditWindowHours !== undefined
              ? Number(body.manualEditWindowHours)
              : undefined,
          adminApprovalRequired:
            body.adminApprovalRequired !== undefined
              ? body.adminApprovalRequired === true
              : undefined,
          gpsRequired: body.gpsRequired !== undefined ? body.gpsRequired === true : undefined,
          gpsRadiusMeters: gpsRequired
            ? body.gpsRadiusMeters !== undefined
              ? Number(body.gpsRadiusMeters)
              : existing.gpsRadiusMeters
            : null,
          gpsMinAccuracyMeters:
            body.gpsMinAccuracyMeters !== undefined
              ? body.gpsMinAccuracyMeters === null
                ? null
                : Number(body.gpsMinAccuracyMeters)
              : undefined,
          fieldOverrides,
        },
        existing,
      );

      if (!updated) {
        sendApiError(reply, request, 404, ErrorCode.InvalidPayload);
        return;
      }

      if (request.actor) {
        await repository.writePolicyAudit({
          actorUserId: request.actor.userId,
          policyId,
          oldValue: repository.toApiPolicy(existing) as unknown as Record<string, unknown>,
          newValue: repository.toApiPolicy(updated) as unknown as Record<string, unknown>,
          correlationId: request.headers["idempotency-key"] as string | undefined,
        });
      }

      sendApiSuccess(reply, request, 200, repository.toApiPolicy(updated));
    },
  );
}
