import Link from "next/link";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";

export default function AccessDeniedPage() {
  return (
    <div className="space-y-6">
      <EmptyState
        title="Access denied"
        description="You do not have permission to view this section. Sign in with an account that has the required role, or return to a safe page."
        actionLabel="Sign in"
        actionHref="/login"
      />
      <div className="flex flex-wrap justify-center gap-2">
        <Button asChild variant="secondary">
          <Link href="/events">Browse events</Link>
        </Button>
        <Button asChild variant="secondary">
          <Link href="/">Home</Link>
        </Button>
      </div>
    </div>
  );
}
