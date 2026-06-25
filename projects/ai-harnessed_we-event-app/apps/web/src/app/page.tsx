import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/layout/page-header";
import { DesignSystemPreview } from "@/components/shell/design-system-preview";

export default function HomePage() {
  return (
    <AppShell role="participant" userDisplayName="Guest">
      <PageHeader
        title="We Event"
        subtitle="Application shell, semantic design tokens, and shared UI primitives are ready. Participant and organizer journeys ship in the next slices."
      />
      <DesignSystemPreview />
    </AppShell>
  );
}
