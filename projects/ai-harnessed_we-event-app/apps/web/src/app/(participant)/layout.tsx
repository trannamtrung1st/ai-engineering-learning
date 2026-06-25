import { ParticipantShell } from "@/components/participant/participant-shell";
import { AuthProvider } from "@/providers/auth-provider";

export default function ParticipantLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthProvider>
      <ParticipantShell>{children}</ParticipantShell>
    </AuthProvider>
  );
}
