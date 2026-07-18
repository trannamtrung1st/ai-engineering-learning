import { eq } from "drizzle-orm";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import type { AttendlyDatabase } from "../db/client";
import {
  classSections,
  classSessions,
  qrSessionTokens,
} from "../db/schema";

export const DEFAULT_QR_TTL_MS = 30_000;

type ActiveQr = {
  token: string;
  expiresAt: Date;
};

// Display cache only: tracks the token currently shown to the lecturer so the
// UI reuses it until TTL instead of rotating on every poll. Check-in validates
// against the persisted qr_session_tokens rows, NOT this map — do not make
// check-in read from here.
const activeQrTokens = new Map<string, ActiveQr>();

export class QrSessionError extends Error {
  constructor(
    public readonly code: "session_not_found" | "not_owner" | "attendance_closed",
  ) {
    super(code);
  }
}

export function hashQrToken(token: string) {
  return createHash("sha256").update(token).digest("hex");
}

function ownedSession(
  db: AttendlyDatabase,
  classSessionId: string,
) {
  return db
    .select({
      sessionId: classSessions.id,
      lecturerId: classSections.lecturerId,
      openedAt: classSessions.attendanceOpenedAt,
      closedAt: classSessions.attendanceClosedAt,
    })
    .from(classSessions)
    .innerJoin(
      classSections,
      eq(classSessions.classSectionId, classSections.id),
    )
    .where(eq(classSessions.id, classSessionId))
    .get();
}

function mintQr(
  db: AttendlyDatabase,
  classSessionId: string,
  now: Date,
  ttlMs: number,
) {
  const token = randomBytes(24).toString("base64url");
  const expiresAt = new Date(now.getTime() + ttlMs);
  db.insert(qrSessionTokens)
    .values({
      id: randomUUID(),
      classSessionId,
      tokenHash: hashQrToken(token),
      expiresAt,
      createdAt: now,
    })
    .run();

  const active = { token, expiresAt };
  activeQrTokens.set(classSessionId, active);
  return active;
}

export function openAttendance(
  db: AttendlyDatabase,
  classSessionId: string,
  lecturerId: string,
  now = new Date(),
  ttlMs = DEFAULT_QR_TTL_MS,
) {
  const session = ownedSession(db, classSessionId);
  if (!session) throw new QrSessionError("session_not_found");
  if (session.lecturerId !== lecturerId) throw new QrSessionError("not_owner");

  db.update(classSessions)
    .set({ attendanceOpenedAt: now, attendanceClosedAt: null })
    .where(eq(classSessions.id, classSessionId))
    .run();

  return mintQr(db, classSessionId, now, ttlMs);
}

export function getCurrentQr(
  db: AttendlyDatabase,
  classSessionId: string,
  lecturerId: string,
  now = new Date(),
  ttlMs = DEFAULT_QR_TTL_MS,
) {
  const session = ownedSession(db, classSessionId);
  if (!session) throw new QrSessionError("session_not_found");
  if (session.lecturerId !== lecturerId) throw new QrSessionError("not_owner");
  if (!session.openedAt || session.closedAt) {
    throw new QrSessionError("attendance_closed");
  }

  const current = activeQrTokens.get(classSessionId);
  if (current && current.expiresAt.getTime() > now.getTime()) return current;
  return mintQr(db, classSessionId, now, ttlMs);
}

export function clearActiveQrCache() {
  activeQrTokens.clear();
}
