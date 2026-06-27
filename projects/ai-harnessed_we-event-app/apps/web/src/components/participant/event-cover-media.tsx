"use client";

import Image from "next/image";
import { CalendarDays } from "lucide-react";

import { cn } from "@/lib/cn";

export interface EventCoverMediaProps {
  coverImageUrl?: string | null;
  alt: string;
  variant: "thumbnail" | "hero";
  className?: string;
}

function CoverPlaceholder({ variant }: { variant: "thumbnail" | "hero" }) {
  return (
    <div
      className={cn(
        "flex w-full items-center justify-center bg-[var(--color-bg-subtle)] text-[var(--color-text-secondary)]",
        variant === "thumbnail" ? "aspect-video rounded-[var(--radius-md)]" : "aspect-[21/9] rounded-[var(--radius-lg)]",
      )}
      aria-hidden
    >
      <CalendarDays className={variant === "thumbnail" ? "h-8 w-8 opacity-60" : "h-12 w-12 opacity-60"} />
    </div>
  );
}

export function EventCoverMedia({
  coverImageUrl,
  alt,
  variant,
  className,
}: EventCoverMediaProps) {
  if (!coverImageUrl) {
    return (
      <div className={className} data-testid="event-cover-placeholder">
        <CoverPlaceholder variant={variant} />
      </div>
    );
  }

  return (
    <div
      className={cn(
        "relative w-full overflow-hidden",
        variant === "thumbnail"
          ? "aspect-video rounded-[var(--radius-md)]"
          : "aspect-[21/9] rounded-[var(--radius-lg)]",
        className,
      )}
      data-testid="event-cover-image"
    >
      <Image
        src={coverImageUrl}
        alt={alt}
        fill
        className="object-cover"
        sizes={variant === "thumbnail" ? "(max-width: 768px) 100vw, 50vw" : "100vw"}
      />
    </div>
  );
}
