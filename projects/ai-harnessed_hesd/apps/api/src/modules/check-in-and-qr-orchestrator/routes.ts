import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { ErrorCode } from "@attendly/domain";
import {
  combineGuards,
  createAuthenticate,
  createAuthorizeGuard,
  type IdentityServices,
} from "../identity/middleware.js";
import { resolveRequestId, sendApiError, sendApiSuccess } from "../identity/http.js";
import type { ApiErrorEnvelope } from "@attendly/domain";
import type { CheckInRepository } from "./repository.js";
import type { GpsPayload } from "./types.js";

const CHECK_IN_MESSAGES: Record<string, string> = {
  [ErrorCode.ExpiredQr]:
    "Mã QR đã hết hạn. Vui lòng quét mã QR hiện tại trên màn hình giảng viên.",
  [ErrorCode.InvalidQr]: "Mã QR không hợp lệ. Vui lòng quét lại mã trên màn hình giảng viên.",
  [ErrorCode.SessionNotOpen]: "Buổi học chưa được mở điểm danh.",
  [ErrorCode.SessionClosed]: "Buổi học đã kết thúc điểm danh.",
  [ErrorCode.NotEnrolled]: "Bạn không có trong danh sách lớp học này.",
  [ErrorCode.DuplicateCheckIn]: "Bạn đã điểm danh buổi học này rồi.",
  [ErrorCode.GpsRequired]: "Cần bật định vị GPS để điểm danh.",
  [ErrorCode.GpsDisabled]: "Dữ liệu GPS không hợp lệ.",
  [ErrorCode.OutOfRadius]: "Vị trí hiện tại ngoài phạm vi cho phép.",
  [ErrorCode.LowAccuracy]: "Độ chính xác GPS không đủ để điểm danh.",
};

function paramsSessionId(request: FastifyRequest) {
  const params = request.params as { sessionId?: string };
  return { classSessionId: params.sessionId };
}

function idempotencyKey(request: FastifyRequest): string | undefined {
  const header = request.headers["idempotency-key"];
  return typeof header === "string" && header.length > 0 ? header : undefined;
}

function sendCheckInError(
  reply: FastifyReply,
  request: FastifyRequest,
  statusCode: number,
  code: string,
  details?: Record<string, unknown>,
): void {
  const body: ApiErrorEnvelope = {
    data: null,
    meta: {
      requestId: resolveRequestId(request),
      timestamp: new Date().toISOString(),
    },
    error: {
      code,
      message: CHECK_IN_MESSAGES[code] ?? code,
      ...(details ? { details } : {}),
    },
  };
  void reply.status(statusCode).send(body);
}

function parseGps(body: Record<string, unknown>): GpsPayload | null | undefined {
  const gps = body.gps;
  if (gps === undefined) return undefined;
  if (gps === null || typeof gps !== "object") return null;
  const record = gps as Record<string, unknown>;
  if (
    typeof record.latitude !== "number" ||
    typeof record.longitude !== "number" ||
    typeof record.accuracyMeters !== "number"
  ) {
    return null;
  }
  return {
    latitude: record.latitude,
    longitude: record.longitude,
    accuracyMeters: record.accuracyMeters,
  };
}

const OUTCOME_STATUS: Record<string, { status: number; code: string }> = {
  ExpiredQr: { status: 422, code: ErrorCode.ExpiredQr },
  SessionNotOpen: { status: 422, code: ErrorCode.SessionNotOpen },
  SessionClosed: { status: 422, code: ErrorCode.SessionClosed },
  InvalidQr: { status: 422, code: ErrorCode.InvalidQr },
  NotEnrolled: { status: 422, code: ErrorCode.NotEnrolled },
  DuplicateCheckIn: { status: 409, code: ErrorCode.DuplicateCheckIn },
  GpsRequired: { status: 422, code: ErrorCode.GpsRequired },
  GpsDisabled: { status: 422, code: ErrorCode.GpsDisabled },
  OutOfRadius: { status: 422, code: ErrorCode.OutOfRadius },
  LowAccuracy: { status: 422, code: ErrorCode.LowAccuracy },
};

export async function registerCheckInRoutes(
  app: FastifyInstance,
  services: IdentityServices,
  repository: CheckInRepository,
): Promise<void> {
  const authenticate = createAuthenticate(services);

  const guardSessionControl = createAuthorizeGuard(services, {
    resource: "SessionControl",
    action: "execute",
    resolveScope: paramsSessionId,
  });

  const guardCheckIn = createAuthorizeGuard(services, {
    resource: "CheckInSubmit",
    action: "execute",
  });

  app.get(
    "/class-sessions/:sessionId/qr/current",
    { preHandler: combineGuards(authenticate, guardSessionControl) },
    async (request, reply) => {
      const params = request.params as { sessionId: string };
      const outcome = await repository.getCurrentQr(params.sessionId);

      if (!outcome.ok) {
        if (outcome.code === "SessionNotFound") {
          sendApiError(reply, request, 404, ErrorCode.SessionNotFound);
          return;
        }
        sendCheckInError(
          reply,
          request,
          422,
          outcome.code === "SessionClosed" ? ErrorCode.SessionClosed : ErrorCode.SessionNotOpen,
        );
        return;
      }

      sendApiSuccess(reply, request, 200, outcome.result);
    },
  );

  app.post(
    "/check-ins",
    { preHandler: combineGuards(authenticate, guardCheckIn) },
    async (request, reply) => {
      const actor = request.actor!;
      const body = (request.body ?? {}) as Record<string, unknown>;
      const qrToken = typeof body.qrToken === "string" ? body.qrToken.trim() : "";

      if (!qrToken) {
        sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
        return;
      }

      const clientTimestamp =
        typeof body.clientTimestamp === "string" ? body.clientTimestamp : undefined;
      const gps = parseGps(body);
      const userAgent = request.headers["user-agent"];

      const outcome = await repository.submitCheckIn({
        studentUserId: actor.userId,
        qrToken,
        clientTimestamp,
        gps,
        deviceUserAgent: typeof userAgent === "string" ? userAgent : null,
        correlationId: resolveRequestId(request),
        idempotencyKey: idempotencyKey(request),
      });

      if (outcome.result.outcome === "Success") {
        sendApiSuccess(reply, request, 200, outcome.result);
        return;
      }

      const mapping = OUTCOME_STATUS[outcome.result.outcome] ?? {
        status: 422,
        code: outcome.result.outcome,
      };
      sendCheckInError(
        reply,
        request,
        mapping.status,
        mapping.code,
        outcome.result.details,
      );
    },
  );
}
