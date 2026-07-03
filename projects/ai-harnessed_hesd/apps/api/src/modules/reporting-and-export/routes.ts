import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { ErrorCode } from "@attendly/domain";
import { createAuthenticate, type IdentityServices } from "../identity/middleware.js";
import {
  authDenied,
  resolveRequestId,
  sendApiError,
  sendApiSuccess,
} from "../identity/http.js";
import { buildPaginationMeta } from "../academic-structure/pagination.js";
import type { ReportingRepository } from "./repository.js";
import { resolveReportExportScope } from "./scope.js";
import { parseReportQuery, validateExportBody } from "./validation.js";

function idempotencyKey(request: FastifyRequest): string | undefined {
  const header = request.headers["idempotency-key"];
  return typeof header === "string" && header.length > 0 ? header : undefined;
}

function paginatedSuccess<T>(
  reply: FastifyReply,
  request: FastifyRequest,
  items: T[],
  page: number,
  pageSize: number,
  totalItems: number,
): void {
  const body = {
    data: items,
    meta: {
      requestId: resolveRequestId(request),
      timestamp: new Date().toISOString(),
      pagination: buildPaginationMeta(page, pageSize, totalItems),
    },
    error: null,
  };
  void reply.status(200).send(body);
}

async function assertScopeAccess(
  request: FastifyRequest,
  reply: FastifyReply,
  services: IdentityServices,
  resource: "ReportView" | "ExportJob",
  filters: Parameters<typeof resolveReportExportScope>[2],
) {
  const actor = request.actor;
  if (!actor) {
    sendApiError(reply, request, 401, ErrorCode.Unauthenticated);
    return null;
  }

  const access = await resolveReportExportScope(actor, services.repository, filters, resource);
  if (!access.allowed) {
    authDenied(reply, request, access.code);
    return null;
  }

  return access.scope;
}

export async function registerReportingRoutes(
  app: FastifyInstance,
  services: IdentityServices,
  repository: ReportingRepository,
): Promise<void> {
  const authenticate = createAuthenticate(services);

  app.get(
    "/reports/attendance",
    { preHandler: authenticate },
    async (request, reply) => {
      const parsed = parseReportQuery(request.query as Record<string, unknown>);
      if (parsed.error) {
        const code =
          parsed.error.code === "InvalidPayload"
            ? ErrorCode.InvalidPayload
            : ErrorCode.InvalidFilter;
        sendApiError(reply, request, 400, code, parsed.error.details);
        return;
      }

      const scope = await assertScopeAccess(
        request,
        reply,
        services,
        "ReportView",
        parsed.filters,
      );
      if (!scope) return;

      const queryFilters = {
        ...parsed.filters,
        ...(scope.studentUserId ? { studentUserId: scope.studentUserId } : {}),
      };

      const result = await repository.queryAttendanceReport({
        scope,
        filters: queryFilters,
        sortBy: parsed.sortBy,
        sortOrder: parsed.sortOrder,
        page: parsed.page,
        pageSize: parsed.pageSize,
      });

      paginatedSuccess(
        reply,
        request,
        result.rows,
        parsed.page,
        parsed.pageSize,
        result.totalItems,
      );
    },
  );

  app.post(
    "/exports/attendance",
    { preHandler: authenticate },
    async (request, reply) => {
      const body = (request.body ?? {}) as Record<string, unknown>;
      const validated = validateExportBody(body);
      if (validated.error) {
        const code =
          validated.error.code === "UnsupportedFormat"
            ? ErrorCode.UnsupportedFormat
            : validated.error.code === "InvalidPayload"
              ? ErrorCode.InvalidPayload
              : ErrorCode.InvalidFilter;
        sendApiError(reply, request, 400, code, validated.error.details);
        return;
      }

      const scope = await assertScopeAccess(
        request,
        reply,
        services,
        "ExportJob",
        validated.filters,
      );
      if (!scope || !request.actor) return;

      const job = await repository.createExportJob({
        actor: request.actor,
        format: validated.format,
        filters: validated.filters,
        scope,
        idempotencyKey: idempotencyKey(request),
        correlationId: request.requestId,
      });

      sendApiSuccess(reply, request, 202, {
        exportJobId: job.exportJobId,
        status: job.status,
        format: job.format,
      });
    },
  );

  app.get<{ Params: { exportJobId: string } }>(
    "/exports/attendance/:exportJobId",
    { preHandler: authenticate },
    async (request, reply) => {
      const actor = request.actor;
      if (!actor) {
        sendApiError(reply, request, 401, ErrorCode.Unauthenticated);
        return;
      }

      const artifact = await repository.getExportArtifactForActor(
        request.params.exportJobId,
        actor.userId,
      );
      if (!artifact) {
        authDenied(reply, request, "OutOfScope");
        return;
      }

      void reply
        .status(200)
        .header("content-type", "text/csv; charset=utf-8")
        .header(
          "content-disposition",
          `attachment; filename="attendance-export-${request.params.exportJobId}.csv"`,
        )
        .send(artifact.csv);
    },
  );
}
