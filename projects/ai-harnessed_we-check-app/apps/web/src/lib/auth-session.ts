import { apiFetch } from "@/lib/api-client";

export async function isAuthenticated(): Promise<boolean> {
  const res = await apiFetch<{ id: string }>("/auth/me");
  return res.ok;
}
