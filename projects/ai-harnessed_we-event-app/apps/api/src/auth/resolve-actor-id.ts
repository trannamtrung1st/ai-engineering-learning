import { createHash } from "node:crypto";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Postgres stores participant/actor ids as UUID. Dev JWT subs (e.g. participant-1)
 * are mapped to a deterministic UUID so local auth and persistence stay aligned.
 */
export function resolveActorId(subOrId: string): string {
  if (UUID_PATTERN.test(subOrId)) {
    return subOrId.toLowerCase();
  }

  const hash = createHash("sha256")
    .update(`we-event:participant:${subOrId}`)
    .digest();
  const bytes = Uint8Array.from(hash.subarray(0, 16));
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;

  const hex = [...bytes]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");

  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20, 32)}`;
}

export function actorIdsMatch(left: string, right: string): boolean {
  return resolveActorId(left) === resolveActorId(right);
}
