import type { CheckInOutcomeState } from "../../components/domain/CheckInResultScreen";

export interface CheckInSuccessCopy {
  state: Extract<CheckInOutcomeState, "success-present" | "success-late">;
  title: string;
  message: string;
}

export function resolveCheckInSuccessCopy(
  attendanceStatus: "Present" | "Late",
): CheckInSuccessCopy {
  if (attendanceStatus === "Late") {
    return {
      state: "success-late",
      title: "Điểm danh thành công — Đi trễ",
      message: "Bạn đã điểm danh thành công cho buổi học này (trễ).",
    };
  }

  return {
    state: "success-present",
    title: "Điểm danh thành công — Có mặt",
    message: "Bạn đã điểm danh thành công cho buổi học này.",
  };
}
