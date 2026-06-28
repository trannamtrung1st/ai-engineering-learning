import { DOMAIN_PACKAGE_VERSION, PASSWORD_POLICY } from "@wecheck/domain";

export function App() {
  return (
    <main>
      <h1>We Check</h1>
      <p>
        Monorepo bootstrap — domain v{DOMAIN_PACKAGE_VERSION}, password min{" "}
        {PASSWORD_POLICY.MIN_LENGTH} (NFR-14)
      </p>
    </main>
  );
}
