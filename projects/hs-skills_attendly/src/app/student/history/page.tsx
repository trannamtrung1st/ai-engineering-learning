import Link from "next/link";
import { redirect } from "next/navigation";
import { getCurrentSession } from "@/auth/session";
import { getDatabase } from "@/db/client";
import {
  ATTENDANCE_STATUSES,
  getStudentAttendanceHistory,
} from "@/domain/attendance-report";

const STATUS_LABELS: Record<string, string> = {
  present: "Present",
  late: "Late",
  absent: "Absent",
  excused: "Excused",
  manual_present: "Manual Present",
};

export default async function StudentHistoryPage() {
  const session = await getCurrentSession();
  if (!session) {
    redirect(`/login?next=${encodeURIComponent("/student/history")}`);
  }
  if (session.role !== "student") {
    redirect("/lecturer/sessions/session-ai-101-01");
  }

  const history = getStudentAttendanceHistory(getDatabase().db, {
    studentId: session.userId,
  });

  return (
    <main>
      <h1>My attendance history</h1>
      <p>
        <Link href="/check-in">Back to check-in</Link>
      </p>
      {history.length === 0 && <p>You are not enrolled in any sections.</p>}
      {history.map((section) => (
        <section key={section.classSectionId}>
          <h2>{section.sectionName}</h2>
          <p>
            {ATTENDANCE_STATUSES.map(
              (status) => `${STATUS_LABELS[status]}: ${section.totals[status]}`,
            ).join(" · ")}
          </p>
          <table>
            <thead>
              <tr>
                <th>Session date</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {section.sessions.map((entry) => (
                <tr key={entry.classSessionId}>
                  <td>{entry.startsAt.toLocaleString()}</td>
                  <td>
                    {entry.status ? STATUS_LABELS[entry.status] : "No record"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
      <form action="/api/auth/logout" method="post">
        <button type="submit">Sign out</button>
      </form>
    </main>
  );
}
