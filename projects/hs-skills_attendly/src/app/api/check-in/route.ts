import { NextResponse } from "next/server";
import { getCurrentSession } from "@/auth/session";
import { getDatabase } from "@/db/client";
import { checkIn } from "@/domain/check-in";

export async function POST(request: Request) {
  const auth = await getCurrentSession();
  if (!auth) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  if (auth.role !== "student") {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }

  let body: { classSessionId?: unknown; token?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_request" }, { status: 400 });
  }

  if (
    typeof body.classSessionId !== "string" ||
    typeof body.token !== "string" ||
    !body.classSessionId ||
    !body.token
  ) {
    return NextResponse.json({ error: "invalid_request" }, { status: 400 });
  }

  const result = checkIn(getDatabase().db, {
    studentId: auth.userId,
    classSessionId: body.classSessionId,
    token: body.token,
  });

  if (!result.ok) {
    return NextResponse.json({ error: result.reason }, { status: 422 });
  }
  return NextResponse.json({
    attendanceRecordId: result.attendanceRecordId,
    status: result.status,
  });
}
