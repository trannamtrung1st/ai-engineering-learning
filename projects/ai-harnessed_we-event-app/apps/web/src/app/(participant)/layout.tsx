import { Suspense } from "react";

import { ParticipantShell } from "@/components/participant/participant-shell";
import { Skeleton } from "@/components/ui/skeleton";

export default function ParticipantLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <Suspense
      fallback={
        <div className="space-y-4 p-6">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-40 w-full" />
        </div>
      }
    >
      <ParticipantShell>{children}</ParticipantShell>
    </Suspense>
  );
}
