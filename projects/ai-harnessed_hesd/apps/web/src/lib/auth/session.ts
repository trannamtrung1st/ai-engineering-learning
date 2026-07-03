export const ACCESS_TOKEN_STORAGE_KEY = "attendly.accessToken";

export function getAccessToken(): string | null {
  if (typeof localStorage === "undefined") {
    return null;
  }
  const token = localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
  return token && token.length > 0 ? token : null;
}

export function setAccessToken(token: string): void {
  localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token);
}

export function clearAccessToken(): void {
  localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
}
