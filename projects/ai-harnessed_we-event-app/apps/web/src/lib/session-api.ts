import { apiFetch } from "@/lib/api-client";

export interface UserRoleAssignment {
  role: string;
  organizationId: string | null;
  assignedEventIds: string[];
}

export interface SessionInfo {
  userId?: string;
  email?: string;
  displayName?: string;
  roles?: UserRoleAssignment[];
  actorId: string;
  role: string;
  assignedEventIds: string[];
}

export interface AuthCredentials {
  email: string;
  password: string;
}

export interface RegisterInput extends AuthCredentials {
  displayName: string;
}

export interface AuthSessionResponse {
  token: string;
  profile: {
    userId: string;
    email: string;
    displayName: string;
    roles: UserRoleAssignment[];
  };
}

export function fetchSession(token: string): Promise<SessionInfo> {
  return apiFetch<SessionInfo>("/me", { token });
}

export function loginWithCredentials(
  credentials: AuthCredentials,
): Promise<AuthSessionResponse> {
  return apiFetch<AuthSessionResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(credentials),
    headers: { "Content-Type": "application/json" },
  });
}

export function registerAccount(
  input: RegisterInput,
): Promise<AuthSessionResponse> {
  return apiFetch<AuthSessionResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}
