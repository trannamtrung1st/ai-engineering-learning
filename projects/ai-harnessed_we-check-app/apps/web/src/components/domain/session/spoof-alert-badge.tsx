import { ShieldAlert } from "lucide-react";
import { cn } from "@/lib/cn";

export interface SpoofAlertBadgeProps {
  className?: string;
}

/** FR-10 / AC-10 — spoof-suspected indicator on instructor monitor rows */
export function SpoofAlertBadge({ className }: SpoofAlertBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full bg-danger-50 px-2 py-0.5 text-small text-danger-700",
        className,
      )}
      data-testid="spoof-alert-badge"
      title="Vị trí nghi ngờ giả mạo — cần xác minh thủ công"
    >
      <ShieldAlert className="h-3.5 w-3.5" aria-hidden="true" />
      <span>Nghi ngờ giả mạo</span>
    </span>
  );
}
