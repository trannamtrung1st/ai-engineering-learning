import { resolvePreviewId } from "@/lib/preview-fixtures";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface ParsedCheckInDeepLink {
  tokenId: string;
  sessionId?: string;
}

function resolveTokenParam(raw: string | null): string | null {
  if (!raw?.trim()) return null;
  const trimmed = raw.trim();
  if (UUID_RE.test(trimmed)) return trimmed;
  return resolvePreviewId(trimmed);
}

function resolveSessionParam(raw: string | null): string | undefined {
  if (!raw?.trim()) return undefined;
  const trimmed = raw.trim();
  if (UUID_RE.test(trimmed)) return trimmed;
  return resolvePreviewId(trimmed) ?? undefined;
}

/** Parse wecheck://check-in?token=…&session=… or bare token UUID (FR-07) */
export function parseCheckInQrPayload(payload: string): ParsedCheckInDeepLink | null {
  const trimmed = payload.trim();
  if (!trimmed) return null;

  if (UUID_RE.test(trimmed)) {
    return { tokenId: trimmed };
  }

  if (!trimmed.includes("://") && !trimmed.includes("?")) {
    const aliasOnly = resolveTokenParam(trimmed);
    if (aliasOnly) {
      return { tokenId: aliasOnly };
    }
  }

  try {
    const url = trimmed.includes("://")
      ? new URL(trimmed)
      : new URL(`wecheck://check-in?${trimmed.replace(/^\?/, "")}`);

    const tokenId = resolveTokenParam(url.searchParams.get("token"));
    if (!tokenId) return null;

    const sessionId = resolveSessionParam(url.searchParams.get("session"));
    return { sessionId, tokenId };
  } catch {
    return null;
  }
}
