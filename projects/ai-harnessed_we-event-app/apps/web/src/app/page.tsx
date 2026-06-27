import Link from "next/link";

import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { DesignSystemPreview } from "@/components/shell/design-system-preview";

export default function HomePage() {
  return (
    <AppShell role="participant" userDisplayName="Guest">
      <PageHeader
        title="We Event"
        subtitle="Event registration, check-in, and feedback for participants and organizers."
        actions={
          <div className="flex flex-wrap gap-2">
            <Button asChild>
              <Link href="/login">Sign in</Link>
            </Button>
            <Button asChild variant="secondary">
              <Link href="/signup">Create account</Link>
            </Button>
          </div>
        }
      />
      <DesignSystemPreview />
    </AppShell>
  );
}
