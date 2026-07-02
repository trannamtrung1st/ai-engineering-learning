import type { UserRole } from "@wecheck/domain";
import { apiFetch, type ApiErrorBody } from "@/lib/api-client";

export interface SetupStatusResponse {
  needsSetup: boolean;
}

export interface FirstAdminPayload {
  institutionalId: string;
  displayName: string;
  email: string;
  password: string;
}

export interface FirstAdminResponse {
  user: {
    id: string;
    institutionalId: string;
    displayName: string;
    email: string;
    role: UserRole;
  };
  session: {
    id: string;
    expiresAt: string;
  };
}

export type SetupMutationResult =
  | { ok: true; data: FirstAdminResponse }
  | { ok: false; status: number; error: ApiErrorBody };

const SETUP_COMPLETE_CACHE_KEY = "wecheck-setup-complete";

export function getCachedSetupComplete(): boolean {
  try {
    return sessionStorage.getItem(SETUP_COMPLETE_CACHE_KEY) === "1";
  } catch {
    return false;
  }
}

export function setCachedSetupComplete(complete: boolean): void {
  try {
    if (complete) {
      sessionStorage.setItem(SETUP_COMPLETE_CACHE_KEY, "1");
    } else {
      sessionStorage.removeItem(SETUP_COMPLETE_CACHE_KEY);
    }
  } catch {
    // ignore storage failures
  }
}

/** FR-17 — poll deployment bootstrap gate */
export async function fetchSetupStatus(): Promise<
  | { ok: true; data: SetupStatusResponse }
  | { ok: false; status: number; error: ApiErrorBody }
> {
  const res = await apiFetch<SetupStatusResponse>("/setup/status");
  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  if (!res.data.needsSetup) {
    setCachedSetupComplete(true);
  }
  return { ok: true, data: res.data };
}

/** FR-17 / AC-17 — create first TrainingOfficeAdmin and establish session */
export async function createFirstAdmin(
  payload: FirstAdminPayload,
): Promise<SetupMutationResult> {
  const res = await apiFetch<FirstAdminResponse>("/setup/first-admin", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  return { ok: true, data: res.data };
}
