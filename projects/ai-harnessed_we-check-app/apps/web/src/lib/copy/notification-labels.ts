import type { AbsenceThresholdPayload } from "@/lib/notifications-api";

/** FR-16 / AC-16 / BR-05 — in-app absence threshold notification copy */
export const notificationCopy = {
  bellLabel: "Thông báo",
  panelTitle: "Thông báo",
  empty: "Không có thông báo mới",
  absenceWarningTitle: "Cảnh báo vắng mặt",
  historyBadge: "Vượt ngưỡng vắng",
  loadError: "Không thể tải thông báo",
  markRead: "Đã đọc",
} as const;

export function formatAbsenceRatePercent(rate: number): string {
  return `${Math.round(rate * 1000) / 10}%`;
}

export function formatAbsenceWarningToast(payload: AbsenceThresholdPayload): string {
  const rate = formatAbsenceRatePercent(payload.absenceRate);
  const threshold = formatAbsenceRatePercent(payload.threshold);
  if (payload.studentDisplayName) {
    return `${payload.studentDisplayName} — ${payload.subjectName}: tỷ lệ vắng ${rate} (ngưỡng ${threshold})`;
  }
  return `${payload.subjectName}: tỷ lệ vắng ${rate} vượt ngưỡng ${threshold}`;
}

export function formatAbsenceWarningDetail(payload: AbsenceThresholdPayload): string {
  const rate = formatAbsenceRatePercent(payload.absenceRate);
  const threshold = formatAbsenceRatePercent(payload.threshold);
  return `${payload.unexcusedAbsenceCount}/${payload.sessionCount} buổi vắng không phép · ngưỡng ${threshold} · hiện tại ${rate}`;
}
