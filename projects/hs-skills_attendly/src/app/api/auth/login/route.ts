import { NextResponse } from "next/server";
import {
  authenticate,
  createSessionToken,
  SESSION_COOKIE,
  sessionCookieOptions,
} from "@/auth/session";
import { getDatabase } from "@/db/client";

function safeNext(value: FormDataEntryValue | null, fallback: string) {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//")
    ? value
    : fallback;
}

export async function POST(request: Request) {
  const form = await request.formData();
  const email = form.get("email");
  const password = form.get("password");
  const next = form.get("next");

  if (typeof email !== "string" || typeof password !== "string") {
    return NextResponse.redirect(new URL("/login?error=invalid", request.url), 303);
  }

  const user = authenticate(getDatabase().db, email, password);
  if (!user) {
    return NextResponse.redirect(new URL("/login?error=invalid", request.url), 303);
  }

  const fallback =
    user.role === "lecturer"
      ? "/lecturer/sessions/session-ai-101-01"
      : "/check-in";
  const response = NextResponse.redirect(
    new URL(safeNext(next, fallback), request.url),
    303,
  );
  response.cookies.set(
    SESSION_COOKIE,
    createSessionToken({ userId: user.userId, role: user.role }),
    sessionCookieOptions,
  );
  return response;
}
