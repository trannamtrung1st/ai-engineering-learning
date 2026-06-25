import { ParticipantShell } from "@/components/participant/participant-shell";

export default function ParticipantLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <ParticipantShell>{children}</ParticipantShell>;
}
