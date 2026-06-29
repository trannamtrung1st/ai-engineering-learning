import { ErrorCode } from "@wecheck/domain";
import type { ErrorDetail } from "../../errors/api-error.js";
import type { ReportFilter } from "./types.js";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const MAX_RANGE_DAYS = 366;

function parseDate(value: string): Date | null {
  if (!DATE_RE.test(value)) {
    return null;
  }
  const date = new Date(`${value}T00:00:00.000Z`);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date;
}

function daysBetween(from: Date, to: Date): number {
  return Math.floor((to.getTime() - from.getTime()) / (24 * 60 * 60 * 1000));
}

export function validateReportFilter(
  input: Record<string, unknown>,
  options?: { requireClassSubject?: boolean },
): { ok: true; value: ReportFilter } | { ok: false; details: ErrorDetail[] } {
  const details: ErrorDetail[] = [];
  const requireClassSubject = options?.requireClassSubject ?? false;

  const classCode =
    typeof input.classCode === "string" && input.classCode.trim()
      ? input.classCode.trim()
      : undefined;
  const subjectCode =
    typeof input.subjectCode === "string" && input.subjectCode.trim()
      ? input.subjectCode.trim()
      : undefined;

  if (requireClassSubject) {
    if (!classCode) {
      details.push({
        field: "classCode",
        code: ErrorCode.ValidationFailed,
        message: "Mã lớp là bắt buộc",
      });
    }
    if (!subjectCode) {
      details.push({
        field: "subjectCode",
        code: ErrorCode.ValidationFailed,
        message: "Mã môn học là bắt buộc",
      });
    }
  }

  const fromRaw = input.from;
  const toRaw = input.to;
  if (typeof fromRaw !== "string" || !fromRaw.trim()) {
    details.push({
      field: "from",
      code: ErrorCode.ValidationFailed,
      message: "Ngày bắt đầu là bắt buộc (YYYY-MM-DD)",
    });
  }
  if (typeof toRaw !== "string" || !toRaw.trim()) {
    details.push({
      field: "to",
      code: ErrorCode.ValidationFailed,
      message: "Ngày kết thúc là bắt buộc (YYYY-MM-DD)",
    });
  }

  if (details.length > 0) {
    return { ok: false, details };
  }

  const from = (fromRaw as string).trim();
  const to = (toRaw as string).trim();
  const fromDate = parseDate(from);
  const toDate = parseDate(to);

  if (!fromDate) {
    details.push({
      field: "from",
      code: ErrorCode.ValidationFailed,
      message: "Ngày bắt đầu không hợp lệ (YYYY-MM-DD)",
    });
  }
  if (!toDate) {
    details.push({
      field: "to",
      code: ErrorCode.ValidationFailed,
      message: "Ngày kết thúc không hợp lệ (YYYY-MM-DD)",
    });
  }

  if (details.length > 0) {
    return { ok: false, details };
  }

  if (fromDate! > toDate!) {
    details.push({
      field: "from",
      code: ErrorCode.ValidationFailed,
      message: "Ngày bắt đầu phải trước hoặc bằng ngày kết thúc",
    });
    details.push({
      field: "to",
      code: ErrorCode.ValidationFailed,
      message: "Ngày kết thúc phải sau hoặc bằng ngày bắt đầu",
    });
    return { ok: false, details };
  }

  if (daysBetween(fromDate!, toDate!) > MAX_RANGE_DAYS) {
    details.push({
      field: "from",
      code: ErrorCode.ValidationFailed,
      message: "Khoảng thời gian tối đa là 366 ngày",
    });
    return { ok: false, details };
  }

  return {
    ok: true,
    value: {
      ...(classCode ? { classCode } : {}),
      ...(subjectCode ? { subjectCode } : {}),
      from,
      to,
    },
  };
}
