import type { PolicyScopeType } from "../api/policy-api.js";

export const POLICY_SCOPE_LABELS: Record<PolicyScopeType, string> = {
  Institution: "Toàn trường",
  Faculty: "Khoa",
  Course: "Học phần",
  ClassSection: "Lớp học phần",
};

export const POLICY_PRECEDENCE_CHAIN: PolicyScopeType[] = [
  "ClassSection",
  "Course",
  "Faculty",
  "Institution",
];

export const POLICY_FIELD_LABELS: Record<string, string> = {
  presentWindowMinutes: "Cửa sổ Có mặt (phút)",
  lateWindowMinutes: "Cửa sổ Muộn (phút)",
  manualEditWindowHours: "Cửa sổ chỉnh sửa thủ công (giờ)",
  gpsRequired: "Bắt buộc GPS",
  gpsRadiusMeters: "Bán kính GPS (m)",
  checkInOpeningOffsetMinutes: "Mở sớm trước giờ học (phút)",
  autoCloseEnabled: "Tự đóng buổi học",
  absenceThresholdPercent: "Ngưỡng vắng mặt (%)",
  excusedCountsTowardThreshold: "Tính vắng có phép vào ngưỡng",
  adminApprovalRequired: "Yêu cầu duyệt quản trị",
};

export const POLICY_FIELD_HELPERS: Record<string, string> = {
  presentWindowMinutes: "Sinh viên điểm danh trong khoảng này được ghi Có mặt (FR-25).",
  lateWindowMinutes: "Sau cửa sổ Có mặt, sinh viên vẫn có thể ghi Muộn trong khoảng này.",
  manualEditWindowHours: "Giảng viên có thể chỉnh sửa thủ công trong số giờ sau khi đóng buổi học.",
  gpsRequired: "Khi bật, sinh viên phải chia sẻ vị trí GPS khi điểm danh (AC-09).",
  gpsRadiusMeters: "Khoảng cách tối đa từ phòng học; ngoài bán kính sẽ bị từ chối (AC-10).",
  absenceThresholdPercent: "Phần trăm vắng mặt kích hoạt cảnh báo cho sinh viên.",
};

export function formatPolicyFieldValue(key: string, value: unknown): string {
  if (typeof value === "boolean") {
    return value ? "Có" : "Không";
  }
  if (value === null || value === undefined) {
    return "—";
  }
  return String(value);
}

export function scopeSourceBadgeLabel(scope: PolicyScopeType): string {
  return POLICY_SCOPE_LABELS[scope];
}
