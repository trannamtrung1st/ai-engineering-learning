import { NextResponse } from "next/server";
import { getCurrentSession } from "@/auth/session";
import { getDatabase } from "@/db/client";
import {
  ManualAttendanceError,
  markManualPresent,
} from "@/domain/manual-attendance";

type RouteContext = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: RouteContext) {
  const auth = await getCurrentSession();
  if (!auth) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  if (auth.role !== "lecturer") {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }

  let body: { studentId?: unknown; reason?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_request" }, { status: 400 });
  }
  if (
    typeof body.studentId !== "string" ||
    typeof body.reason !== "string"
  ) {
    return NextResponse.json({ error: "invalid_request" }, { status: 400 });
  }

  try {
    const { id } = await params;
    const result = markManualPresent(getDatabase().db, {
      lecturerId: auth.userId,
      classSessionId: id,
      studentId: body.studentId,
      reason: body.reason,
    });
    return NextResponse.json({ ...result, status: "manual_present" });
  } catch (error) {
    if (error instanceof ManualAttendanceError) {
      const status =
        error.code === "session_not_found"
          ? 404
          : error.code === "invalid_reason"
            ? 400
            : 403;
      return NextResponse.json({ error: error.code }, { status });
    }
    throw error;
  }
}
