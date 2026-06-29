const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface ParsedCheckInDeepLink {
  tokenId: string;
  sessionId?: string;
}

/** Parse wecheck://check-in?token=…&session=… or bare token UUID (FR-07) */
export function parseCheckInQrPayload(payload: string): ParsedCheckInDeepLink | null {
  const trimmed = payload.trim();
  if (!trimmed) return null;

  if (UUID_RE.test(trimmed)) {
    return { tokenId: trimmed };
  }

  try {
    const url = trimmed.includes("://")
      ? new URL(trimmed)
      : new URL(`wecheck://check-in?${trimmed.replace(/^\?/, "")}`);

    const tokenId = url.searchParams.get("token");
    if (!tokenId || !UUID_RE.test(tokenId)) return null;

    const sessionId = url.searchParams.get("session") ?? undefined;
    return { sessionId: sessionId && UUID_RE.test(sessionId) ? sessionId : undefined, tokenId };
  } catch {
    return null;
  }
}
