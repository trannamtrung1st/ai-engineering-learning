import { NextResponse } from "next/server";
import { getCurrentSession } from "@/auth/session";
import { getDatabase } from "@/db/client";
import { getCurrentQr, QrSessionError } from "@/domain/qr-session";

type RouteContext = { params: Promise<{ id: string }> };

export async function GET(_request: Request, { params }: RouteContext) {
  const auth = await getCurrentSession();
  if (!auth) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  if (auth.role !== "lecturer") {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }

  try {
    const { id } = await params;
    const qr = getCurrentQr(getDatabase().db, id, auth.userId);
    return NextResponse.json({
      token: qr.token,
      expiresAt: qr.expiresAt.toISOString(),
    });
  } catch (error) {
    if (error instanceof QrSessionError) {
      const status =
        error.code === "session_not_found"
          ? 404
          : error.code === "attendance_closed"
            ? 409
            : 403;
      return NextResponse.json({ error: error.code }, { status });
    }
    throw error;
  }
}
