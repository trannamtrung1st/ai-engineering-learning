"use client";

import { useRouter } from "next/navigation";

import { EmptyState } from "@/components/ui/empty-state";

export interface RefreshEmptyStateProps {
  title: string;
  description: string;
  actionLabel?: string;
}

export function RefreshEmptyState({
  title,
  description,
  actionLabel = "Refresh",
}: RefreshEmptyStateProps) {
  const router = useRouter();

  return (
    <EmptyState
      title={title}
      description={description}
      actionLabel={actionLabel}
      onAction={() => router.refresh()}
    />
  );
}
