import { redirect } from "next/navigation";
import { getCurrentSession } from "@/auth/session";
import { getDatabase } from "@/db/client";
import {
  AttendanceReportError,
  getSectionReport,
  type SectionReport,
} from "@/domain/attendance-report";

type SectionReportPageProps = {
  params: Promise<{ id: string }>;
};

export default async function SectionReportPage({
  params,
}: SectionReportPageProps) {
  const { id } = await params;
  const session = await getCurrentSession();
  if (!session) {
    redirect(
      `/login?next=${encodeURIComponent(`/lecturer/sections/${id}/report`)}`,
    );
  }
  if (session.role !== "lecturer") redirect("/check-in");

  let report: SectionReport;
  try {
    report = getSectionReport(getDatabase().db, {
      classSectionId: id,
      lecturerId: session.userId,
    });
  } catch (error) {
    if (error instanceof AttendanceReportError) {
      return (
        <main>
          <h1>Attendance report</h1>
          <p role="alert">
            {error.code === "not_owner"
              ? "You do not own this class section."
              : "Class section not found."}
          </p>
        </main>
      );
    }
    throw error;
  }

  return (
    <main>
      <h1>Attendance report</h1>
      <p>Section: {report.sectionName}</p>
      <form action={`/api/sections/${id}/report/export`} method="post">
        <button type="submit">Download CSV</button>
      </form>
      <table>
        <thead>
          <tr>
            <th>Student</th>
            <th>Present</th>
            <th>Late</th>
            <th>Absent</th>
            <th>Excused</th>
            <th>Manual Present</th>
            <th>Attendance rate</th>
          </tr>
        </thead>
        <tbody>
          {report.rows.map((row) => (
            <tr key={row.studentId}>
              <td>{row.studentName}</td>
              <td>{row.counts.present}</td>
              <td>{row.counts.late}</td>
              <td>{row.counts.absent}</td>
              <td>{row.counts.excused}</td>
              <td>{row.counts.manual_present}</td>
              <td>
                {row.attendanceRate === null
                  ? "—"
                  : `${Math.round(row.attendanceRate * 100)}%`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <form action="/api/auth/logout" method="post">
        <button type="submit">Sign out</button>
      </form>
    </main>
  );
}
