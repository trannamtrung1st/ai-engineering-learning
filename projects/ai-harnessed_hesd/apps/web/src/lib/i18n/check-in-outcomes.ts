import { ErrorCode } from "@attendly/domain";
import type { CheckInOutcomeState } from "../../components/domain/CheckInResultScreen";

export interface CheckInOutcomeCopy {
  state: CheckInOutcomeState;
  title: string;
  message: string;
  retryAllowed: boolean;
}

const VI_COPY: Record<string, CheckInOutcomeCopy> = {
  [ErrorCode.ExpiredQr]: {
    state: "failure-expired-qr",
    title: "Mã QR đã hết hạn",
    message: "Vui lòng quét mã mới từ giảng viên.",
    retryAllowed: true,
  },
  [ErrorCode.NotEnrolled]: {
    state: "failure-not-enrolled",
    title: "Không thuộc lớp học phần",
    message:
      "Bạn không thuộc lớp học phần này. Nếu bạn nghĩ đây là nhầm lẫn, vui lòng liên hệ phòng đào tạo.",
    retryAllowed: false,
  },
  [ErrorCode.DuplicateCheckIn]: {
    state: "failure-duplicate",
    title: "Đã điểm danh",
    message: "Bạn đã điểm danh buổi học này rồi.",
    retryAllowed: false,
  },
  [ErrorCode.SessionNotOpen]: {
    state: "failure-session-not-open",
    title: "Buổi học chưa mở",
    message: "Buổi học chưa mở điểm danh.",
    retryAllowed: false,
  },
  [ErrorCode.SessionClosed]: {
    state: "failure-session-not-open",
    title: "Buổi học đã đóng",
    message: "Buổi học đã đóng điểm danh.",
    retryAllowed: false,
  },
  [ErrorCode.GpsDisabled]: {
    state: "failure-gps-denied",
    title: "Cần quyền vị trí",
    message: "Hãy bật quyền vị trí hoặc báo giảng viên hỗ trợ thủ công.",
    retryAllowed: true,
  },
  [ErrorCode.GpsRequired]: {
    state: "failure-gps-denied",
    title: "Cần quyền vị trí",
    message: "Hãy bật quyền vị trí hoặc báo giảng viên hỗ trợ thủ công.",
    retryAllowed: true,
  },
  [ErrorCode.OutOfRadius]: {
    state: "failure-out-of-radius",
    title: "Ngoài phạm vi lớp",
    message: "Hãy đến gần phòng học hoặc liên hệ giảng viên.",
    retryAllowed: true,
  },
  [ErrorCode.LowAccuracy]: {
    state: "failure-out-of-radius",
    title: "Vị trí chưa chính xác",
    message: "Không thể xác định vị trí chính xác. Hãy thử lại ở ngoài trời hoặc gần cửa sổ.",
    retryAllowed: true,
  },
  [ErrorCode.Unauthenticated]: {
    state: "failure-unauthenticated",
    title: "Đăng nhập để tiếp tục",
    message: "Vui lòng đăng nhập để tiếp tục.",
    retryAllowed: false,
  },
};

export function resolveCheckInOutcomeCopy(
  errorCode: string,
  locale: "vi-VN" | "en" = "vi-VN",
): CheckInOutcomeCopy {
  if (locale !== "vi-VN") {
    return (
      VI_COPY[errorCode] ?? {
        state: "failure-session-not-open",
        title: "Check-in failed",
        message: errorCode,
        retryAllowed: false,
      }
    );
  }

  return (
    VI_COPY[errorCode] ?? {
      state: "failure-session-not-open",
      title: "Không thể điểm danh",
      message: "Đã xảy ra lỗi khi điểm danh. Vui lòng thử lại.",
      retryAllowed: false,
    }
  );
}

export function loginRequiredMessage(locale: "vi-VN" | "en" = "vi-VN"): string {
  return locale === "vi-VN" ? "Đăng nhập để tiếp tục" : "Sign in to continue";
}
