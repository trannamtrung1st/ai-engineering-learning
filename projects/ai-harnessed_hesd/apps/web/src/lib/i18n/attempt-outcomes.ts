import { ErrorCode } from "@attendly/domain";

const OUTCOME_LABELS: Record<string, string> = {
  [ErrorCode.ExpiredQr]: "QR hết hạn",
  [ErrorCode.NotEnrolled]: "Không thuộc lớp",
  [ErrorCode.DuplicateCheckIn]: "Đã điểm danh",
  [ErrorCode.SessionNotOpen]: "Buổi chưa mở",
  [ErrorCode.SessionClosed]: "Buổi đã đóng",
  [ErrorCode.GpsDisabled]: "Từ chối GPS",
  [ErrorCode.GpsRequired]: "Thiếu GPS",
  [ErrorCode.OutOfRadius]: "Ngoài phạm vi",
  [ErrorCode.LowAccuracy]: "GPS kém chính xác",
  Success: "Thành công",
};

const OUTCOME_TOOLTIPS: Record<string, string> = {
  [ErrorCode.ExpiredQr]: "Sinh viên quét mã QR đã hết hạn. Yêu cầu quét mã mới từ giảng viên.",
  [ErrorCode.NotEnrolled]: "Sinh viên không thuộc lớp học phần này.",
  [ErrorCode.DuplicateCheckIn]: "Sinh viên đã điểm danh thành công trước đó.",
  [ErrorCode.GpsDisabled]: "Trình duyệt từ chối quyền vị trí. Có thể điều chỉnh thủ công sau khi xác minh.",
  [ErrorCode.GpsRequired]: "Chính sách yêu cầu GPS nhưng thiết bị không cung cấp vị trí.",
  [ErrorCode.OutOfRadius]: "Vị trí sinh viên ngoài bán kính phòng học.",
  [ErrorCode.LowAccuracy]: "Độ chính xác GPS không đủ để xác nhận.",
};

export function attemptOutcomeLabel(outcome: string | null | undefined): string | null {
  if (!outcome || outcome === "Success") return null;
  return OUTCOME_LABELS[outcome] ?? outcome;
}

export function attemptOutcomeTooltip(outcome: string | null | undefined): string | null {
  if (!outcome || outcome === "Success") return null;
  return OUTCOME_TOOLTIPS[outcome] ?? `Lần thử gần nhất: ${outcome}`;
}

export function isRejectedAttemptOutcome(outcome: string | null | undefined): boolean {
  if (!outcome || outcome === "Success") return false;
  return outcome in OUTCOME_LABELS || Boolean(OUTCOME_TOOLTIPS[outcome]);
}

export function formatOutOfRadiusReviewMeta(
  distanceMeters: number | null | undefined,
  allowedRadiusMeters: number | null | undefined,
): string | null {
  if (distanceMeters == null || allowedRadiusMeters == null) {
    return null;
  }
  const distance = Math.round(distanceMeters);
  const allowed = Math.round(allowedRadiusMeters);
  return `${distance}m · giới hạn ${allowed}m`;
}
