import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { getPermissionGuideContent, type PermissionGuideType } from "@/lib/copy/permission-guide";
import type { MobilePlatform } from "@/lib/detect-platform";
import { cn } from "@/lib/cn";

export interface PermissionGuideModalProps {
  open: boolean;
  type: PermissionGuideType;
  platform: MobilePlatform;
  onClose: () => void;
  className?: string;
}

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** NFR-19 — platform-specific camera/GPS permission recovery modal */
export function PermissionGuideModal({
  open,
  type,
  platform,
  onClose,
  className,
}: PermissionGuideModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const content = getPermissionGuideContent(type, platform);

  useEffect(() => {
    if (!open) return;
    panelRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }

      if (event.key !== "Tab" || !panelRef.current) return;

      const focusables = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE),
      );
      if (focusables.length === 0) return;

      const first = focusables[0];
      const last = focusables[focusables.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="permission-guide-title"
        aria-describedby="permission-guide-steps"
        tabIndex={-1}
        className={cn(
          "w-full max-w-md max-h-[90vh] overflow-y-auto rounded-lg border border-border bg-surface p-6 shadow-lg",
          className,
        )}
        data-testid={`permission-guide-modal-${type}`}
        data-platform={platform}
      >
        <h2 id="permission-guide-title" className="text-heading text-text-primary">
          {content.title}
        </h2>
        <ol
          id="permission-guide-steps"
          className="mt-4 list-decimal space-y-2 pl-5 text-body text-text-primary"
        >
          {content.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        <div className="mt-6 flex flex-col gap-2">
          <Button
            ref={closeRef}
            type="button"
            className="w-full min-h-touch"
            onClick={onClose}
          >
            Đóng
          </Button>
          <p className="text-small text-text-secondary">
            Nếu vẫn không điểm danh được, vui lòng liên hệ giảng viên để được ghi nhận thủ công.
          </p>
        </div>
      </div>
    </div>
  );
}
