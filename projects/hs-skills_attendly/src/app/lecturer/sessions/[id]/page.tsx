import { redirect } from "next/navigation";
import { getCurrentSession } from "@/auth/session";
import { getDatabase } from "@/db/client";
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

  const roster = getSessionRoster(getDatabase().db, id);

  return (
    <main>
      <h1>Lecturer attendance</h1>
      <p>Session: {id}</p>
      <QrDisplay classSessionId={id} />
      <ManualAttendancePanel classSessionId={id} roster={roster} />
      <form action="/api/auth/logout" method="post">
        <button type="submit">Sign out</button>
      </form>
    </main>
  );
}
