import { Suspense } from "react";

import { SignupPageClient } from "@/components/auth/signup-page-client";
import { Skeleton } from "@/components/ui/skeleton";

export default function SignupPage() {
  return (
    <Suspense
      fallback={
        <div className="space-y-4">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-48 w-full" />
        </div>
      }
    >
      <SignupPageClient />
    </Suspense>
  );
}
