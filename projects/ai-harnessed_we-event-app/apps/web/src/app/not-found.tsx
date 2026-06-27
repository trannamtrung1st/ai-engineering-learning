import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";

export default function NotFound() {
  return (
    <AppShell role="participant" userDisplayName="Guest">
      <PageHeader title="Page not found" />
      <EmptyState
        title="This page does not exist"
        description="The link may be outdated or you may not have access to this section."
        actionLabel="Return home"
        actionHref="/"
      />
    </AppShell>
  );
}
