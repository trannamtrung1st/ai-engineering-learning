import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchNotifications,
  type NotificationItem,
} from "@/lib/notifications-api";

export const NOTIFICATIONS_QUERY_KEY = ["notifications"] as const;
export const NOTIFICATIONS_POLL_MS = 5_000;
export const SESSION_CLOSED_NOTIFICATION_EVENT = "wecheck:session-closed";

export function useNotifications(enabled = true) {
  return useQuery({
    queryKey: NOTIFICATIONS_QUERY_KEY,
    queryFn: async () => {
      const result = await fetchNotifications({ limit: 50 });
      if (!result.ok) {
        throw result;
      }
      return result.data;
    },
    enabled,
    refetchInterval: enabled ? NOTIFICATIONS_POLL_MS : false,
    retry: false,
  });
}

export function useInvalidateNotifications() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_QUERY_KEY });
}

export function selectUnreadNotifications(items: NotificationItem[]): NotificationItem[] {
  return items.filter((item) => item.readAt === null);
}

export function selectAbsenceWarningsBySubject(
  items: NotificationItem[],
  subjectCode: string,
): NotificationItem[] {
  return items.filter(
    (item) =>
      item.type === "AbsenceThresholdWarning" &&
      item.payload.subjectCode === subjectCode,
  );
}
