import type {
  AttendanceStatus,
  SessionStatus,
  UserRole,
} from "@wecheck/domain";

/** Vietnamese UI labels per docs/ui-ux/01-ui-ux-foundation.md §2 */
export const sessionStatusLabels: Record<SessionStatus, string> = {
  Draft: "Nháp",
  Active: "Đang diễn ra",
  Closed: "Đã kết thúc",
  Cancelled: "Đã hủy",
};

export const attendanceStatusLabels: Record<AttendanceStatus, string> = {
  Pending: "Chưa điểm danh",
  Present: "Có mặt",
  Absent: "Vắng",
  Excused: "Vắng có phép",
  Rejected: "Từ chối",
};

export const roleLabels: Record<UserRole, string> = {
  Student: "Sinh viên",
  Instructor: "Giảng viên",
  TrainingOfficeAdmin: "Quản trị đào tạo",
};

export const appCopy = {
  productName: "We Check",
  productSubtitle: "Điểm danh số cho buổi học",
  skipToContent: "Bỏ qua đến nội dung chính",
  mainContent: "Nội dung chính",
  logout: "Đăng xuất",
  adminSection: "Quản trị",
  qrCountdownPrefix: "Mã mới sau",
  qrCountdownSuffix: "giây",
  exitFullscreen: "Thoát toàn màn hình",
  projectionResolutionWarning:
    "Độ phân giải màn hình dưới 1280×720 — hãy đặt máy chiếu ở 1280×720 để mã QR rõ nhất.",
  validatingQrToken: "Đang xác thực mã QR…",
  forbiddenTitle: "Không có quyền truy cập",
  forbiddenMessage:
    "Bạn không có quyền xem nội dung này. Liên hệ phòng đào tạo nếu cần hỗ trợ.",
  forbiddenHome: "Về trang chủ",
  notFoundTitle: "Không tìm thấy trang",
  notFoundMessage: "Đường dẫn không tồn tại hoặc đã bị gỡ.",
  errorBoundaryTitle: "Đã xảy ra lỗi",
  errorBoundaryMessage: "Không thể hiển thị trang. Vui lòng tải lại.",
  errorBoundaryReload: "Tải lại trang",
  shellOverviewTitle: "Hệ thống giao diện We Check",
  shellOverviewDescription:
    "Khung bố cục theo vai trò và thành phần dùng chung — chưa có màn hình nghiệp vụ.",
} as const;

export const studentNavItems = [
  { to: "/check-in", label: "Điểm danh" },
  { to: "/history", label: "Lịch sử" },
] as const;

export const instructorNavItems = [
  { to: "/sessions", label: "Buổi học" },
  { to: "/reports", label: "Báo cáo" },
] as const;

export const adminNavItems = [
  { to: "/admin/users", label: "Người dùng" },
  { to: "/admin/rosters", label: "Danh sách lớp" },
  { to: "/admin/reports", label: "Báo cáo" },
  { to: "/admin/export", label: "Xuất CSV" },
  { to: "/admin/policy", label: "Chính sách" },
] as const;
