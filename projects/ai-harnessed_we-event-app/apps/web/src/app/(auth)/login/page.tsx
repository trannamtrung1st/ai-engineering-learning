import { Suspense } from "react";

import { LoginPageClient } from "@/components/auth/login-page-client";
import { Skeleton } from "@/components/ui/skeleton";

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="space-y-4">
          <Skeleton className="h-8 w-40" />
          <Skeleton className="h-40 w-full" />
        </div>
      }
    >
      <LoginPageClient />
    </Suspense>
  );
}
