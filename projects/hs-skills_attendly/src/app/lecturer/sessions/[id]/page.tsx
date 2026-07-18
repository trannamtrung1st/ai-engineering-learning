import { eq } from "drizzle-orm";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getCurrentSession } from "@/auth/session";
import { getDatabase } from "@/db/client";
import { classSessions } from "@/db/schema";
import { getSessionRoster } from "@/domain/manual-attendance";
import { ManualAttendancePanel } from "@/components/ManualAttendancePanel";
import { QrDisplay } from "@/components/QrDisplay";

type LecturerSessionPageProps = {
  params: Promise<{ id: string }>;
};

export default async function LecturerSessionPage({
  params,
}: LecturerSessionPageProps) {
  const { id } = await params;
  const session = await getCurrentSession();
  if (!session) {
    redirect(`/login?next=${encodeURIComponent(`/lecturer/sessions/${id}`)}`);
  }
  if (session.role !== "lecturer") redirect("/check-in");

  const db = getDatabase().db;
  const roster = getSessionRoster(db, id);
  const classSection = db
    .select({ classSectionId: classSessions.classSectionId })
    .from(classSessions)
    .where(eq(classSessions.id, id))
    .get();

  return (
    <main>
      <h1>Lecturer attendance</h1>
      <p>Session: {id}</p>
      {classSection && (
        <p>
          <Link
            href={`/lecturer/sections/${classSection.classSectionId}/report`}
          >
            View section attendance report
          </Link>
        </p>
      )}
      <QrDisplay classSessionId={id} />
      <ManualAttendancePanel classSessionId={id} roster={roster} />
      <form action="/api/auth/logout" method="post">
        <button type="submit">Sign out</button>
      </form>
    </main>
  );
}
