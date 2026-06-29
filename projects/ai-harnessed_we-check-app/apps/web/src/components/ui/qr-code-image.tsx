import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";
import {
  encodeQrDataUrl,
  QR_FULLSCREEN_SIZE,
  QR_PREVIEW_SIZE,
} from "@/lib/qr-encode";

export interface QrCodeImageProps {
  value: string | undefined;
  size?: number;
  variant?: "preview" | "fullscreen";
  ariaLabel?: string;
  className?: string;
  fading?: boolean;
  imageKey?: number;
  tokenId?: string;
}

const defaultAriaLabel = "Mã QR điểm danh buổi học";

/** NFR-20 — scannable QR with error correction H and 4-module quiet zone */
export function QrCodeImage({
  value,
  size,
  variant = "preview",
  ariaLabel = defaultAriaLabel,
  className,
  fading = false,
  imageKey = 0,
  tokenId,
}: QrCodeImageProps) {
  const resolvedSize =
    size ?? (variant === "fullscreen" ? QR_FULLSCREEN_SIZE : QR_PREVIEW_SIZE);
  const [dataUrl, setDataUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!value) {
      setDataUrl(null);
      return;
    }

    let cancelled = false;
    void encodeQrDataUrl(value, resolvedSize).then((url) => {
      if (!cancelled) {
        setDataUrl(url);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [value, resolvedSize, imageKey]);

  if (!value) {
    return (
      <div
        data-testid="qr-code-placeholder"
        className={cn(
          "flex items-center justify-center rounded-lg bg-qr-fg/10",
          className,
        )}
        style={{ width: resolvedSize, height: resolvedSize }}
        aria-hidden="true"
      />
    );
  }

  return (
    <img
      key={`${imageKey}-${tokenId ?? "qr"}`}
      data-testid="qr-code-image"
      data-token-id={tokenId}
      src={dataUrl ?? undefined}
      width={resolvedSize}
      height={resolvedSize}
      alt={ariaLabel}
      className={cn(
        "rounded-lg transition-opacity duration-300",
        fading ? "opacity-0" : "opacity-100",
        !dataUrl && "invisible",
        className,
      )}
    />
  );
}
