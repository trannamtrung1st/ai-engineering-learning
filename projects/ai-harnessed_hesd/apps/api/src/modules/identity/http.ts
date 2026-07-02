import { randomUUID } from "node:crypto";
import type { FastifyReply, FastifyRequest } from "fastify";
import { ErrorCode, successEnvelope, type ApiErrorEnvelope } from "@attendly/domain";
import type { ErrorCode as ErrorCodeType } from "@attendly/domain";

const ERROR_MESSAGES: Record<string, string> = {
  [ErrorCode.Unauthenticated]: "Yêu cầu đăng nhập.",
  [ErrorCode.Forbidden]: "Không có quyền thực hiện thao tác này.",
  [ErrorCode.OutOfScope]: "Dữ liệu nằm ngoài phạm vi được phép.",
};

export function resolveRequestId(request: FastifyRequest): string {
  const header = request.headers["x-request-id"];
  if (typeof header === "string" && header.length > 0) {
    return header;
  }
  return randomUUID();
}

export function sendApiError(
  reply: FastifyReply,
  request: FastifyRequest,
  statusCode: number,
  code: ErrorCodeType,
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
      message: ERROR_MESSAGES[code] ?? code,
      ...(details ? { details } : {}),
    },
  };
  void reply.status(statusCode).send(body);
}

export function sendApiSuccess<T>(
  reply: FastifyReply,
  request: FastifyRequest,
  statusCode: number,
  data: T,
): void {
  void reply.status(statusCode).send(successEnvelope(data, resolveRequestId(request)));
}

export function unauthenticated(reply: FastifyReply, request: FastifyRequest): void {
  sendApiError(reply, request, 401, ErrorCode.Unauthenticated);
}

export function forbidden(reply: FastifyReply, request: FastifyRequest, details?: Record<string, unknown>): void {
  sendApiError(reply, request, 403, ErrorCode.Forbidden, details);
}

export function outOfScope(reply: FastifyReply, request: FastifyRequest, details?: Record<string, unknown>): void {
  sendApiError(reply, request, 403, ErrorCode.OutOfScope, details);
}

export function authDenied(
  reply: FastifyReply,
  request: FastifyRequest,
  code: "Forbidden" | "OutOfScope",
  details?: Record<string, unknown>,
): void {
  if (code === "OutOfScope") {
    outOfScope(reply, request, details);
  } else {
    forbidden(reply, request, details);
  }
}
