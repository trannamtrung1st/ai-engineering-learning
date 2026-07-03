import { apiRequest } from "./client.js";

export interface LoginSuccessData {
  accessToken: string;
  expiresInSeconds: number;
  roles: string[];
}

export interface LoginResult {
  ok: true;
  accessToken: string;
  roles: string[];
}

export interface LoginFailure {
  ok: false;
  code: string;
  message: string;
}

export async function loginStudent(
  email: string,
  password: string,
): Promise<LoginResult | LoginFailure> {
  const envelope = await apiRequest<LoginSuccessData>("/auth/login", {
    method: "POST",
    body: { email, password },
    accessToken: null,
  });

  if (envelope.error || !envelope.data?.accessToken) {
    return {
      ok: false,
      code: envelope.error?.code ?? "LoginFailed",
      message: envelope.error?.message ?? "Đăng nhập thất bại.",
    };
  }

  return {
    ok: true,
    accessToken: envelope.data.accessToken,
    roles: envelope.data.roles,
  };
}
