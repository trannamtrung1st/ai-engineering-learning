import { apiFetch, type ApiErrorBody, type ApiErrorDetail } from "@/lib/api-client";

export interface AbsencePolicyDto {
  thresholdPercent: number;
  autoWarningEnabled: boolean;
}

export type PolicyMutationResult =
  | { ok: true; data: AbsencePolicyDto }
  | { ok: false; status: number; error: ApiErrorBody };

export async function getAbsencePolicy(): Promise<
  { ok: true; data: AbsencePolicyDto } | { ok: false; status: number; error: ApiErrorBody }
> {
  const result = await apiFetch<AbsencePolicyDto>("/policy/absence-threshold");
  if (result.ok) {
    return { ok: true, data: result.data };
  }
  return { ok: false, status: result.status, error: result.data };
}

export async function updateAbsencePolicy(
  payload: AbsencePolicyDto,
): Promise<PolicyMutationResult> {
  const result = await apiFetch<AbsencePolicyDto>("/policy/absence-threshold", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (result.ok) {
    return { ok: true, data: result.data };
  }
  return { ok: false, status: result.status, error: result.data };
}

export function mapPolicyDetailsToFieldErrors(
  details?: ApiErrorDetail[],
): Record<string, string> {
  if (!details?.length) {
    return {};
  }
  return Object.fromEntries(details.map((d) => [d.field, d.message]));
}
