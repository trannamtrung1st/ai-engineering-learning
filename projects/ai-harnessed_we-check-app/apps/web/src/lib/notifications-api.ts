import { NotificationType, type NotificationType as NotificationTypeValue } from "@wecheck/domain";
import { apiFetch, type ApiErrorBody } from "@/lib/api-client";

export interface AbsenceThresholdPayload {
  subjectCode: string;
  subjectName: string;
  absenceRate: number;
  threshold: number;
  sessionCount: number;
  unexcusedAbsenceCount: number;
  sourceSessionId: string;
  studentId?: string;
  studentDisplayName?: string;
}

export interface NotificationItem {
  id: string;
  type: NotificationTypeValue;
  payload: AbsenceThresholdPayload;
  readAt: string | null;
  createdAt: string;
}

export interface NotificationsResponse {
  items: NotificationItem[];
  nextCursor: string | null;
  totalCount: number;
}

export type NotificationsFetchResult =
  | { ok: true; data: NotificationsResponse }
  | { ok: false; status: number; error: ApiErrorBody };

export async function fetchNotifications(params?: {
  limit?: number;
  cursor?: string;
}): Promise<NotificationsFetchResult> {
  const search = new URLSearchParams();
  search.set("limit", String(params?.limit ?? 50));
  if (params?.cursor) {
    search.set("cursor", params.cursor);
  }

  const result = await apiFetch<NotificationsResponse>(
    `/notifications?${search.toString()}`,
  );
  if (result.ok) {
    return { ok: true, data: result.data };
  }
  return { ok: false, status: result.status, error: result.data };
}

export async function markNotificationRead(
  notificationId: string,
): Promise<{ ok: true } | { ok: false; status: number; error: ApiErrorBody }> {
  const result = await apiFetch<Record<string, never>>(
    `/notifications/${notificationId}/read`,
    { method: "PATCH" },
  );
  if (result.ok) {
    return { ok: true };
  }
  return { ok: false, status: result.status, error: result.data };
}

export function isAbsenceThresholdWarning(
  item: NotificationItem,
): item is NotificationItem & { type: typeof NotificationType.AbsenceThresholdWarning } {
  return item.type === NotificationType.AbsenceThresholdWarning;
}
