import { ErrorCode } from "@wecheck/domain";
import type { ErrorDetail } from "../../errors/api-error.js";
import type { NotificationListQuery } from "./types.js";

const DEFAULT_LIMIT = 50;
const MAX_LIMIT = 200;
const MIN_THRESHOLD = 1;
const MAX_THRESHOLD = 100;

function fail(field: string, code: string, message: string): ErrorDetail {
  return { field, code, message };
}

export function validateNotificationListQuery(
  query: Record<string, unknown>,
): { ok: true; value: Required<Pick<NotificationListQuery, "limit">> & NotificationListQuery } | { ok: false; details: ErrorDetail[] } {
  const failures: ErrorDetail[] = [];
  let limit = DEFAULT_LIMIT;
  let cursor: string | undefined;

  if (query.limit !== undefined) {
    const parsed = Number(query.limit);
    if (!Number.isInteger(parsed) || parsed < 1 || parsed > MAX_LIMIT) {
      failures.push(
        fail("limit", ErrorCode.InvalidPagination, "Tham số phân trang không hợp lệ"),
      );
    } else {
      limit = parsed;
    }
  }

  if (query.cursor !== undefined) {
    if (query.cursor === "null" || query.cursor === "") {
      cursor = undefined;
    } else if (typeof query.cursor !== "string") {
      failures.push(
        fail("cursor", ErrorCode.InvalidPagination, "Tham số phân trang không hợp lệ"),
      );
    } else {
      cursor = query.cursor;
    }
  }

  if (failures.length > 0) {
    return { ok: false, details: failures };
  }

  return {
    ok: true,
    value: {
      limit,
      ...(cursor !== undefined ? { cursor } : {}),
    },
  };
}

export function validateAbsenceThresholdBody(
  body: unknown,
): { ok: true; value: { thresholdPercent: number; autoWarningEnabled: boolean } } | { ok: false; details: ErrorDetail[] } {
  if (body === null || typeof body !== "object") {
    return {
      ok: false,
      details: [
        fail("thresholdPercent", ErrorCode.ValidationFailed, "Trường bắt buộc"),
      ],
    };
  }

  const record = body as Record<string, unknown>;
  const raw = record.thresholdPercent;

  if (raw === undefined || raw === null) {
    return {
      ok: false,
      details: [
        fail("thresholdPercent", ErrorCode.ValidationFailed, "Trường bắt buộc"),
      ],
    };
  }

  if (typeof raw !== "number" || !Number.isInteger(raw)) {
    return {
      ok: false,
      details: [
        fail(
          "thresholdPercent",
          ErrorCode.ValidationFailed,
          "Giá trị phải là số nguyên từ 1 đến 100",
        ),
      ],
    };
  }

  if (raw < MIN_THRESHOLD || raw > MAX_THRESHOLD) {
    return {
      ok: false,
      details: [
        fail(
          "thresholdPercent",
          ErrorCode.ValidationFailed,
          "Giá trị phải là số nguyên từ 1 đến 100",
        ),
      ],
    };
  }

  const autoRaw = record.autoWarningEnabled;
  if (autoRaw !== undefined && autoRaw !== null && typeof autoRaw !== "boolean") {
    return {
      ok: false,
      details: [
        fail(
          "autoWarningEnabled",
          ErrorCode.ValidationFailed,
          "Giá trị phải là true hoặc false",
        ),
      ],
    };
  }

  return {
    ok: true,
    value: {
      thresholdPercent: raw,
      autoWarningEnabled:
        autoRaw === undefined || autoRaw === null ? true : autoRaw,
    },
  };
}

export function decodeNotificationCursor(
  cursor: string,
): { createdAt: string; id: string } | null {
  try {
    const decoded = JSON.parse(
      Buffer.from(cursor, "base64url").toString("utf8"),
    ) as { createdAt?: string; id?: string };
    if (
      typeof decoded.createdAt !== "string" ||
      typeof decoded.id !== "string"
    ) {
      return null;
    }
    return { createdAt: decoded.createdAt, id: decoded.id };
  } catch {
    return null;
  }
}

export function encodeNotificationCursor(createdAt: string, id: string): string {
  return Buffer.from(JSON.stringify({ createdAt, id }), "utf8").toString(
    "base64url",
  );
}
