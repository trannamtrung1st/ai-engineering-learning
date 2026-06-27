import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import OrganizerExportPageClient from "./export-page-client";

export default function OrganizerExportPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <OrganizerExportPageClient />
    </Suspense>
  );
}
