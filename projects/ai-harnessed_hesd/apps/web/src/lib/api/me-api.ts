import { apiRequest } from "./client.js";

export interface MeResponseData {
  userId: string;
  email: string;
  displayName: string;
  roles: string[];
  scopes: { scopeType: string; scopeId: string | null }[];
  facultyIds?: string[];
  classSectionIds?: string[];
}

export type MeResult =
  | { ok: true; roles: string[]; classSectionIds: string[]; displayName: string }
  | { ok: false; code: string; message: string };

export async function fetchCurrentUser(): Promise<MeResult> {
  const envelope = await apiRequest<MeResponseData>("/me");
  if (envelope.data && !envelope.error) {
    return {
      ok: true,
      roles: envelope.data.roles,
      classSectionIds: envelope.data.classSectionIds ?? [],
      displayName: envelope.data.displayName,
    };
  }
  return {
    ok: false,
    code: envelope.error?.code ?? "RequestFailed",
    message: envelope.error?.message ?? "Không thể tải thông tin người dùng.",
  };
}
