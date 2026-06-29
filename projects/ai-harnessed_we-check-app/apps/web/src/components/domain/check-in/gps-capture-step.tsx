import { Spinner } from "@/components/ui/spinner";

export type GpsCaptureState =
  | "requesting"
  | "acquiring"
  | "ready"
  | "submitting"
  | "denied";

export interface GpsCaptureStepProps {
  state?: GpsCaptureState;
  attempt?: number;
}

const stateMessages: Record<GpsCaptureState, string> = {
  requesting: "Đang yêu cầu quyền định vị…",
  acquiring: "Đang xác minh vị trí…",
  ready: "Vị trí đã sẵn sàng",
  submitting: "Đang gửi điểm danh…",
  denied: "Không thể truy cập vị trí",
};

/** GPS capture step per ui-states §4.2 (FR-08, AC-08) */
export function GpsCaptureStep({ state = "requesting", attempt = 0 }: GpsCaptureStepProps) {
  const retryLabel =
    attempt > 0 && attempt < 3 && state === "requesting"
      ? `Thử lại (${attempt}/3)`
      : null;

  return (
    <div
      data-testid="gps-capture-step"
      className="flex flex-col items-center gap-4 py-8"
      aria-busy={state === "submitting" ? true : undefined}
    >
      <Spinner className="h-10 w-10" />
      <p className="text-body text-text-primary">{stateMessages[state]}</p>
      {retryLabel ? (
        <p className="text-small text-text-secondary" data-testid="gps-retry-label">
          {retryLabel}
        </p>
      ) : null}
    </div>
  );
}
