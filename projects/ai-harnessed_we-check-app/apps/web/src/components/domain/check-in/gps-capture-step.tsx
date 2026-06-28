import { Spinner } from "@/components/ui/spinner";

export type GpsCaptureState =
  | "requesting"
  | "acquiring"
  | "submitting"
  | "denied";

export interface GpsCaptureStepProps {
  state?: GpsCaptureState;
}

const stateMessages: Record<GpsCaptureState, string> = {
  requesting: "Đang yêu cầu quyền định vị…",
  acquiring: "Đang xác minh vị trí…",
  submitting: "Đang gửi điểm danh…",
  denied: "Không thể truy cập vị trí",
};

/** GPS capture step per ui-states §4.2 */
export function GpsCaptureStep({ state = "requesting" }: GpsCaptureStepProps) {
  return (
    <div
      data-testid="gps-capture-step"
      className="flex flex-col items-center gap-4 py-8"
      aria-busy={state === "submitting" ? true : undefined}
    >
      <Spinner className="h-10 w-10" />
      <p className="text-body text-text-primary">{stateMessages[state]}</p>
    </div>
  );
}
