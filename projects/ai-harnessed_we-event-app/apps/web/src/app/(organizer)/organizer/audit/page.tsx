import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import OrganizerAuditPageClient from "./audit-page-client";

export default function OrganizerAuditPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <OrganizerAuditPageClient />
    </Suspense>
  );
}
