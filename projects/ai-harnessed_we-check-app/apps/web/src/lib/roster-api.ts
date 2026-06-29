import type { RosterImportStatus } from "@wecheck/domain";
import type { ApiErrorBody } from "@/lib/api-client";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export interface ImportErrorDetail {
  rowNumber: number;
  errorCode: string;
  message: string;
}

export interface ImportBatchDto {
  batchId: string;
  status: RosterImportStatus;
  totalRows?: number;
  successRows: number;
  errorRows: number;
  errorDetails: ImportErrorDetail[];
  message?: string;
}

export interface EnrollmentStudentDto {
  id: string;
  institutionalId: string;
  displayName: string;
}

export interface EnrollmentDto {
  enrollmentId: string;
  student: EnrollmentStudentDto;
  enrolledAt: string;
}

export interface EnrollmentsResponse {
  class: { id: string; code: string; name: string };
  subject: { id: string; code: string; name: string };
  enrollments: EnrollmentDto[];
  totalCount: number;
}

export type RosterApiResult<T> =
  | { ok: true; status: number; data: T }
  | { ok: false; status: number; error: ApiErrorBody };

async function parseJson<T>(res: Response): Promise<T & ApiErrorBody> {
  return (await res.json()) as T & ApiErrorBody;
}

/** POST /roster/import — async CSV import (optional dryRun validation) */
export async function postRosterImport(
  file: File,
  options?: { dryRun?: boolean },
): Promise<RosterApiResult<ImportBatchDto>> {
  const formData = new FormData();
  formData.append("file", file);
  if (options?.dryRun) {
    formData.append("dryRun", "true");
  }

  const res = await fetch(`${API_BASE}/roster/import`, {
    method: "POST",
    credentials: "include",
    body: formData,
  });

  const data = await parseJson<ImportBatchDto>(res);
  if (res.ok) {
    return { ok: true, status: res.status, data };
  }
  return { ok: false, status: res.status, error: data };
}

/** GET /roster/imports/:batchId */
export async function fetchImportBatch(
  batchId: string,
): Promise<RosterApiResult<ImportBatchDto>> {
  const res = await fetch(`${API_BASE}/roster/imports/${batchId}`, {
    credentials: "include",
  });
  const data = await parseJson<ImportBatchDto>(res);
  if (res.ok) {
    return { ok: true, status: res.status, data };
  }
  return { ok: false, status: res.status, error: data };
}

/** GET /enrollments?classId=&subjectId= */
export async function fetchEnrollments(
  classId: string,
  subjectId: string,
): Promise<RosterApiResult<EnrollmentsResponse>> {
  const params = new URLSearchParams({ classId, subjectId });
  const res = await fetch(`${API_BASE}/enrollments?${params}`, {
    credentials: "include",
  });
  const data = await parseJson<EnrollmentsResponse>(res);
  if (res.ok) {
    return { ok: true, status: res.status, data };
  }
  return { ok: false, status: res.status, error: data };
}

const DEFAULT_POLL_INTERVAL_MS = 300;
const DEFAULT_MAX_POLL_ATTEMPTS = 100;

/** Poll import batch until Completed or Failed */
export async function pollImportBatchUntilComplete(
  batchId: string,
  options?: { intervalMs?: number; maxAttempts?: number },
): Promise<RosterApiResult<ImportBatchDto>> {
  const intervalMs = options?.intervalMs ?? DEFAULT_POLL_INTERVAL_MS;
  const maxAttempts = options?.maxAttempts ?? DEFAULT_MAX_POLL_ATTEMPTS;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const result = await fetchImportBatch(batchId);
    if (!result.ok) {
      return result;
    }
    if (
      result.data.status === "Completed" ||
      result.data.status === "Failed"
    ) {
      return result;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  return {
    ok: false,
    status: 408,
    error: {
      errorCode: "ImportTimeout",
      message: "Hết thời gian chờ xử lý nhập danh sách",
    },
  };
}
