import { OrganizerAuthProvider } from "@/providers/organizer-auth-provider";
import { OrganizerShell } from "@/components/organizer/organizer-shell";

export default function OrganizerLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <OrganizerAuthProvider>
      <OrganizerShell>{children}</OrganizerShell>
    </OrganizerAuthProvider>
  );
}
