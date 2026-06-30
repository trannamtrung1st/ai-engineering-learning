import { CheckCircle2 } from "lucide-react";
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

const spinnerStates: GpsCaptureState[] = ["requesting", "acquiring", "submitting"];

function resolveAriaBusy(state: GpsCaptureState): boolean | undefined {
  if (state === "ready" || state === "denied") return false;
  if (spinnerStates.includes(state)) return true;
  return undefined;
}

/** GPS capture step per ui-states §4.2 (FR-08, AC-08f) */
export function GpsCaptureStep({ state = "requesting", attempt = 0 }: GpsCaptureStepProps) {
  const retryLabel =
    attempt > 0 && attempt < 3 && state === "requesting"
      ? `Thử lại (${attempt}/3)`
      : null;

  const showSpinner = spinnerStates.includes(state);

  return (
    <div
      data-testid="gps-capture-step"
      className="flex flex-col items-center gap-4 py-8"
      aria-busy={resolveAriaBusy(state)}
    >
      {showSpinner ? (
        <Spinner className="h-10 w-10" />
      ) : state === "ready" ? (
        <CheckCircle2
          className="h-10 w-10 text-success-600"
          aria-hidden="true"
          data-testid="gps-ready-icon"
        />
      ) : null}
      <p className="text-body text-text-primary">{stateMessages[state]}</p>
      {retryLabel ? (
        <p className="text-small text-text-secondary" data-testid="gps-retry-label">
          {retryLabel}
        </p>
      ) : null}
    </div>
  );
}
