import {
  AttendanceStatus,
  ErrorCode,
  type AttendanceStatus as AttendanceStatusType,
} from "@wecheck/domain";
import type { ManualEditInput, StudentHistoryQuery } from "./types.js";

type ValidationFailure = {
  field: string;
  code: string;
  message: string;
};

type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; details: ValidationFailure[] };

function fail(
  field: string,
  code: string,
  message: string,
): { ok: false; details: ValidationFailure[] } {
  return { ok: false, details: [{ field, code, message }] };
}

const MANUAL_STATUSES = new Set<string>([
  AttendanceStatus.Present,
  AttendanceStatus.Absent,
  AttendanceStatus.Excused,
  AttendanceStatus.Rejected,
]);

export function validateManualEditBody(body: unknown): ParseResult<ManualEditInput> {
  if (!body || typeof body !== "object") {
    return fail("status", ErrorCode.ValidationFailed, "Dữ liệu không hợp lệ");
  }

  const input = body as Record<string, unknown>;
  const failures: ValidationFailure[] = [];

  if (typeof input.status !== "string" || !MANUAL_STATUSES.has(input.status)) {
    failures.push({
      field: "status",
      code: ErrorCode.InvalidEnum,
      message: "Giá trị enum không hợp lệ",
    });
  }

  let note: string | undefined;
  if (input.note !== undefined && input.note !== null) {
    if (typeof input.note !== "string") {
      failures.push({
        field: "note",
        code: ErrorCode.InvalidLength,
        message: "Độ dài dữ liệu không hợp lệ",
      });
    } else {
      const trimmed = input.note.trim();
      if (trimmed.length > 500) {
        failures.push({
          field: "note",
          code: ErrorCode.InvalidLength,
          message: "Độ dài dữ liệu không hợp lệ",
        });
      } else {
        note = trimmed || undefined;
      }
    }
  }

  if (failures.length > 0) {
    return { ok: false, details: failures };
  }

  return {
    ok: true,
    value: {
      status: input.status as AttendanceStatusType,
      ...(note !== undefined ? { note } : {}),
    },
  };
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export function validateHistoryQuery(
  query: Record<string, unknown>,
): ParseResult<StudentHistoryQuery> {
  const failures: ValidationFailure[] = [];
  let limit = 50;
  let cursor: string | undefined;
  let subjectId: string | undefined;
  let from: string | undefined;
  let to: string | undefined;

  if (query.limit !== undefined) {
    const parsed = Number.parseInt(String(query.limit), 10);
    if (Number.isNaN(parsed) || parsed < 1 || parsed > 200) {
      failures.push({
        field: "limit",
        code: ErrorCode.InvalidPagination,
        message: "Tham số phân trang không hợp lệ",
      });
    } else {
      limit = parsed;
    }
  }

  if (query.cursor !== undefined) {
    if (query.cursor === "null" || query.cursor === "") {
      cursor = undefined;
    } else if (typeof query.cursor !== "string") {
      failures.push({
        field: "cursor",
        code: ErrorCode.InvalidPagination,
        message: "Tham số phân trang không hợp lệ",
      });
    } else {
      cursor = query.cursor;
    }
  }

  if (query.subjectId !== undefined) {
    if (typeof query.subjectId !== "string" || query.subjectId.length === 0) {
      failures.push({
        field: "subjectId",
        code: ErrorCode.InvalidFormat,
        message: "Định dạng trường không hợp lệ",
      });
    } else {
      subjectId = query.subjectId;
    }
  }

  if (query.from !== undefined) {
    if (typeof query.from !== "string" || !DATE_RE.test(query.from)) {
      failures.push({
        field: "from",
        code: ErrorCode.InvalidTimestamp,
        message: "Thời gian không hợp lệ",
      });
    } else {
      from = query.from;
    }
  }

  if (query.to !== undefined) {
    if (typeof query.to !== "string" || !DATE_RE.test(query.to)) {
      failures.push({
        field: "to",
        code: ErrorCode.InvalidTimestamp,
        message: "Thời gian không hợp lệ",
      });
    } else {
      to = query.to;
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
      ...(subjectId !== undefined ? { subjectId } : {}),
      ...(from !== undefined ? { from } : {}),
      ...(to !== undefined ? { to } : {}),
    },
  };
}
