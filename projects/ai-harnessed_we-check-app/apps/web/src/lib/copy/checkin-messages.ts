/** Vietnamese check-in outcome messages per ui-states §4.3 and error-handling §4.4 */
export type CheckInOutcomeCode =
  | "Present"
  | "ExpiredQr"
  | "TokenAlreadyUsed"
  | "OutOfRadius"
  | "GpsDisabled"
  | "DuplicateCheckIn"
  | "SpoofSuspected"
  | "SessionNotActive"
  | "NotEnrolled"
  | "NetworkError";

export interface CheckInOutcomeCopy {
  title: string;
  message: string;
  cta: string;
  variant: "success" | "warning" | "danger" | "info";
}

export const checkInOutcomeMessages: Record<CheckInOutcomeCode, CheckInOutcomeCopy> = {
  Present: {
    title: "Điểm danh thành công",
    message: "Bạn đã được ghi nhận có mặt tại buổi học này.",
    cta: "Xong",
    variant: "success",
  },
  ExpiredQr: {
    title: "Mã QR đã hết hạn",
    message: "Mã QR đã hết hạn, vui lòng quét mã mới",
    cta: "Quét lại",
    variant: "warning",
  },
  TokenAlreadyUsed: {
    title: "Mã QR đã được sử dụng",
    message: "Mã QR đã được sử dụng. Vui lòng quét mã mới trên màn hình giảng viên.",
    cta: "Quét lại",
    variant: "danger",
  },
  OutOfRadius: {
    title: "Ngoài phạm vi phòng học",
    message: "Bạn đang ở ngoài phạm vi cho phép. Vui lòng di chuyển gần phòng học hơn.",
    cta: "Thử lại",
    variant: "warning",
  },
  GpsDisabled: {
    title: "GPS chưa bật",
    message: "Vui lòng bật GPS và cấp quyền định vị để điểm danh",
    cta: "Hướng dẫn cấp quyền",
    variant: "danger",
  },
  DuplicateCheckIn: {
    title: "Đã điểm danh",
    message: "Bạn đã điểm danh buổi học này rồi",
    cta: "Xem lịch sử",
    variant: "info",
  },
  SpoofSuspected: {
    title: "Cảnh báo bảo mật",
    message: "Phát hiện dấu hiệu bất thường. Vui lòng liên hệ giảng viên.",
    cta: "Liên hệ giảng viên",
    variant: "danger",
  },
  SessionNotActive: {
    title: "Buổi học chưa mở",
    message: "Buổi học chưa được mở hoặc đã kết thúc.",
    cta: "Đóng",
    variant: "warning",
  },
  NotEnrolled: {
    title: "Không trong danh sách",
    message: "Bạn không có trong danh sách lớp học này.",
    cta: "Đóng",
    variant: "danger",
  },
  NetworkError: {
    title: "Lỗi kết nối",
    message: "Không thể kết nối máy chủ. Vui lòng thử lại.",
    cta: "Thử lại",
    variant: "danger",
  },
};

export const authMessages = {
  invalidCredentials: "Email hoặc mật khẩu không đúng",
  accountDeactivated: "Tài khoản đã bị vô hiệu hóa",
  sessionExpired: "Phiên đăng nhập đã hết hạn",
  emailLabel: "Email hoặc tên đăng nhập",
  passwordLabel: "Mật khẩu",
  submitLabel: "Đăng nhập",
  loginTitle: "Đăng nhập",
} as const;
