import { eq } from "drizzle-orm";
import { cookies } from "next/headers";
import { createHmac, scryptSync, timingSafeEqual } from "node:crypto";
import type { AttendlyDatabase } from "../db/client";
import { users } from "../db/schema";

export const SESSION_COOKIE = "attendly_session";
const SESSION_DURATION_MS = 8 * 60 * 60 * 1000;

export type Session = {
  userId: string;
  role: "student" | "lecturer";
  expiresAt: number;
};

function secret() {
  const configured = process.env.SESSION_SECRET;
  if (configured) return configured;
  if (process.env.NODE_ENV === "production") {
    throw new Error("SESSION_SECRET must be set in production");
  }
  return "attendly-local-demo-secret-change-me";
}

function sign(value: string) {
  return createHmac("sha256", secret()).update(value).digest("base64url");
}

export function createSessionToken(
  user: Pick<Session, "userId" | "role">,
  now = Date.now(),
) {
  const payload = Buffer.from(
    JSON.stringify({ ...user, expiresAt: now + SESSION_DURATION_MS } satisfies Session),
  ).toString("base64url");
  return `${payload}.${sign(payload)}`;
}

export function verifySessionToken(token: string | undefined, now = Date.now()) {
  if (!token) return null;
  const [payload, signature] = token.split(".");
  if (!payload || !signature) return null;

  const expected = Buffer.from(sign(payload));
  const received = Buffer.from(signature);
  if (expected.length !== received.length || !timingSafeEqual(expected, received)) {
    return null;
  }

  try {
    const session = JSON.parse(
      Buffer.from(payload, "base64url").toString("utf8"),
    ) as Session;
    if (
      !session.userId ||
      !["student", "lecturer"].includes(session.role) ||
      session.expiresAt <= now
    ) {
      return null;
    }
    return session;
  } catch {
    return null;
  }
}

export async function getCurrentSession() {
  const cookieStore = await cookies();
  return verifySessionToken(cookieStore.get(SESSION_COOKIE)?.value);
}

function verifyPassword(password: string, storedHash: string) {
  const [algorithm, salt, expectedHex] = storedHash.split(":");
  if (algorithm !== "scrypt" || !salt || !expectedHex) return false;

  const expected = Buffer.from(expectedHex, "hex");
  const actual = scryptSync(password, salt, expected.length);
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}

export function authenticate(
  db: AttendlyDatabase,
  email: string,
  password: string,
) {
  const user = db
    .select()
    .from(users)
    .where(eq(users.email, email.trim().toLowerCase()))
    .get();

  if (!user || !verifyPassword(password, user.passwordHash)) return null;
  return { userId: user.id, role: user.role, name: user.name };
}

export const sessionCookieOptions = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
  maxAge: SESSION_DURATION_MS / 1000,
};
