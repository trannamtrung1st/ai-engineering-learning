import type { UserImportStatus } from "@wecheck/domain";
import type { ApiErrorBody } from "@/lib/api-client";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export interface UserImportErrorDetail {
  rowNumber: number;
  field?: string;
  errorCode: string;
  message: string;
}

export interface UserImportBatchDto {
  batchId: string;
  status: UserImportStatus;
  totalRows?: number;
  successRows: number;
  errorRows: number;
  createdCount?: number;
  updatedCount?: number;
  errorDetails: UserImportErrorDetail[];
  message?: string;
}

export type UserImportApiResult<T> =
  | { ok: true; status: number; data: T }
  | { ok: false; status: number; error: ApiErrorBody };

async function parseJson<T>(res: Response): Promise<T & ApiErrorBody> {
  return (await res.json()) as T & ApiErrorBody;
}

/** POST /users/import — async CSV import (optional dryRun validation) */
export async function postUserImport(
  file: File,
  options?: { dryRun?: boolean },
): Promise<UserImportApiResult<UserImportBatchDto>> {
  const formData = new FormData();
  formData.append("file", file);
  if (options?.dryRun) {
    formData.append("dryRun", "true");
  }

  const res = await fetch(`${API_BASE}/users/import`, {
    method: "POST",
    credentials: "include",
    body: formData,
  });

  const data = await parseJson<UserImportBatchDto>(res);
  if (res.ok) {
    return { ok: true, status: res.status, data };
  }
  return { ok: false, status: res.status, error: data };
}

/** GET /users/imports/:batchId */
export async function fetchUserImportBatch(
  batchId: string,
): Promise<UserImportApiResult<UserImportBatchDto>> {
  const res = await fetch(`${API_BASE}/users/imports/${batchId}`, {
    credentials: "include",
  });
  const data = await parseJson<UserImportBatchDto>(res);
  if (res.ok) {
    return { ok: true, status: res.status, data };
  }
  return { ok: false, status: res.status, error: data };
}

const DEFAULT_POLL_INTERVAL_MS = 300;
const DEFAULT_MAX_POLL_ATTEMPTS = 100;

/** Poll user import batch until Completed or Failed */
export async function pollUserImportBatchUntilComplete(
  batchId: string,
  options?: { intervalMs?: number; maxAttempts?: number },
): Promise<UserImportApiResult<UserImportBatchDto>> {
  const intervalMs = options?.intervalMs ?? DEFAULT_POLL_INTERVAL_MS;
  const maxAttempts = options?.maxAttempts ?? DEFAULT_MAX_POLL_ATTEMPTS;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const result = await fetchUserImportBatch(batchId);
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
    error: { errorCode: "ImportPollTimeout", message: "Import timed out" },
  };
}
