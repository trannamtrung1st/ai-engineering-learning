"use client";

import { useRouter } from "next/navigation";

import { AppShell } from "@/components/layout/app-shell";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const router = useRouter();

  return (
    <AppShell role="participant" userDisplayName="Guest">
      <PageHeader title="Something went wrong" />
      <EmptyFailureBlock
        variant="failure"
        title="We could not load this page"
        description={
          error.message ||
          "An unexpected error occurred. Try again or return to the home page."
        }
      >
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" onClick={reset}>
            Try again
          </Button>
          <Button size="sm" variant="secondary" onClick={() => router.push("/")}>
            Go home
          </Button>
        </div>
      </EmptyFailureBlock>
    </AppShell>
  );
}
