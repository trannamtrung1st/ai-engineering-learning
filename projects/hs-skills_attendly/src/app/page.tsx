import Link from "next/link";

export default function HomePage() {
  return (
    <main>
      <h1>Attendly</h1>
      <p>Smart campus attendance demo.</p>
      <ul>
        <li>
          <Link href="/login?next=/lecturer/sessions/session-ai-101-01">
            Lecturer demo
          </Link>
        </li>
        <li>
          <Link href="/login?next=/check-in">Student demo</Link>
        </li>
      </ul>
      <p>Use a seeded account and password “attendly-demo”.</p>
    </main>
  );
}
