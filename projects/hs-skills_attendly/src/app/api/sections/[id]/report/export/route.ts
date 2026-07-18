import { NextResponse } from "next/server";
import { getCurrentSession } from "@/auth/session";
import { getDatabase } from "@/db/client";
import {
  AttendanceReportError,
  exportSectionReportCsv,
} from "@/domain/attendance-report";

type RouteContext = { params: Promise<{ id: string }> };

export async function POST(_request: Request, { params }: RouteContext) {
  const auth = await getCurrentSession();
  if (!auth) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  if (auth.role !== "lecturer") {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }

  try {
    const { id } = await params;
    const { csv } = exportSectionReportCsv(getDatabase().db, {
      classSectionId: id,
      lecturerId: auth.userId,
    });
    return new NextResponse(csv, {
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename="attendance-report-${id}.csv"`,
      },
    });
  } catch (error) {
    if (error instanceof AttendanceReportError) {
      return NextResponse.json(
        { error: error.code },
        { status: error.code === "section_not_found" ? 404 : 403 },
      );
    }
    throw error;
  }
}
