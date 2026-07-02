import { ErrorCode } from "@attendly/domain";

export function App() {
  return (
    <main className="shell">
      <header className="shell__header">
        <p className="shell__eyebrow">Attendly</p>
        <h1>Smart Campus Attendance</h1>
        <p className="shell__lede">
          Monorepo foundation is ready. Shared contracts include stable error codes such as{" "}
          <code>{ErrorCode.SessionNotOpen}</code>.
        </p>
      </header>
    </main>
  );
}
