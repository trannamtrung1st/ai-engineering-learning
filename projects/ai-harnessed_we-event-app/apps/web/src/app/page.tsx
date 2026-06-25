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
          <Button asChild>
            <Link href="/events">Browse events</Link>
          </Button>
        }
      />
      <DesignSystemPreview />
    </AppShell>
  );
}
