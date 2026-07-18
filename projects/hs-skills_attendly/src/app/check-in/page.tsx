import { redirect } from "next/navigation";
import { getCurrentSession } from "@/auth/session";
import { CheckInForm } from "@/components/CheckInForm";

type CheckInPageProps = {
  searchParams: Promise<{ session?: string; token?: string }>;
};

export default async function CheckInPage({ searchParams }: CheckInPageProps) {
  const query = await searchParams;
  const nextPath = `/check-in?${new URLSearchParams({
    ...(query.session ? { session: query.session } : {}),
    ...(query.token ? { token: query.token } : {}),
  }).toString()}`;
  const session = await getCurrentSession();
  if (!session) redirect(`/login?next=${encodeURIComponent(nextPath)}`);
  if (session.role !== "student") {
    redirect("/lecturer/sessions/session-ai-101-01");
  }

  return (
    <main>
      <h1>Student check-in</h1>
      <p>Confirm the class session and submit the current QR token.</p>
      <CheckInForm
        initialSessionId={query.session ?? ""}
        initialToken={query.token ?? ""}
      />
      <form action="/api/auth/logout" method="post">
        <button type="submit">Sign out</button>
      </form>
    </main>
  );
}
