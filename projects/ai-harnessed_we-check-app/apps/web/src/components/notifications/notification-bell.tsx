import { Bell } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { toast } from "sonner";
import { IconButton } from "@/components/ui/icon-button";
import { Spinner } from "@/components/ui/spinner";
import {
  formatAbsenceWarningDetail,
  formatAbsenceWarningToast,
  notificationCopy,
} from "@/lib/copy/notification-labels";
import {
  isAbsenceThresholdWarning,
  markNotificationRead,
  type NotificationItem,
} from "@/lib/notifications-api";
import {
  selectUnreadNotifications,
  SESSION_CLOSED_NOTIFICATION_EVENT,
  useNotifications,
} from "@/hooks/use-notifications";
import { cn } from "@/lib/cn";

const SEEN_NOTIFICATIONS_KEY = "wecheck.notifications.toast-seen.v1";

function readSeenNotificationIds(): Set<string> {
  try {
    const raw = sessionStorage.getItem(SEEN_NOTIFICATIONS_KEY);
    if (!raw) {
      return new Set();
    }
    const parsed = JSON.parse(raw) as string[];
    return new Set(parsed);
  } catch {
    return new Set();
  }
}

function writeSeenNotificationIds(ids: Set<string>): void {
  sessionStorage.setItem(SEEN_NOTIFICATIONS_KEY, JSON.stringify([...ids]));
}

function NotificationRow({
  item,
  onRead,
}: {
  item: NotificationItem;
  onRead: (id: string) => void;
}) {
  if (!isAbsenceThresholdWarning(item)) {
    return null;
  }

  const unread = item.readAt === null;

  return (
    <li
      className={cn(
        "rounded-md border border-border p-3",
        unread ? "bg-warning-50 border-warning-200" : "bg-surface-raised",
      )}
      data-testid={`notification-item-${item.id}`}
    >
      <p className="text-small font-semibold text-warning-800">
        {notificationCopy.absenceWarningTitle}
      </p>
      <p className="mt-1 text-body text-text-primary">
        {formatAbsenceWarningToast(item.payload)}
      </p>
      <p className="mt-1 text-small text-text-secondary">
        {formatAbsenceWarningDetail(item.payload)}
      </p>
      {unread ? (
        <button
          type="button"
          className="mt-2 text-small font-medium text-primary-700 hover:underline"
          data-testid={`notification-mark-read-${item.id}`}
          onClick={() => onRead(item.id)}
        >
          {notificationCopy.markRead}
        </button>
      ) : null}
    </li>
  );
}

/** FR-16 / AC-16 — in-app notification bell and inbox panel */
export function NotificationBell() {
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const query = useNotifications();
  const seenRef = useRef<Set<string>>(readSeenNotificationIds());
  const burstToastRef = useRef(false);

  const items = query.data?.items ?? [];
  const unread = selectUnreadNotifications(items);
  const unreadCount = unread.length;

  function toastUnreadAbsenceWarnings(allowReshow = false) {
    for (const item of unread) {
      if (!isAbsenceThresholdWarning(item)) {
        continue;
      }
      if (!allowReshow && seenRef.current.has(item.id)) {
        continue;
      }
      seenRef.current.add(item.id);
      writeSeenNotificationIds(seenRef.current);
      toast.warning(notificationCopy.absenceWarningTitle, {
        id: `absence-warning-${item.id}`,
        description: formatAbsenceWarningToast(item.payload),
        duration: 8000,
      });
    }
  }

  useEffect(() => {
    if (!query.data) {
      return;
    }
    toastUnreadAbsenceWarnings(burstToastRef.current);
    burstToastRef.current = false;
  }, [query.data, unread]);

  useEffect(() => {
    function handleSessionClosed() {
      burstToastRef.current = true;
      void query.refetch();
    }

    window.addEventListener(SESSION_CLOSED_NOTIFICATION_EVENT, handleSessionClosed);
    return () =>
      window.removeEventListener(SESSION_CLOSED_NOTIFICATION_EVENT, handleSessionClosed);
  }, [query]);

  useEffect(() => {
    if (!open) {
      return;
    }

    function handlePointerDown(event: MouseEvent) {
      if (!panelRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [open]);

  async function handleMarkRead(notificationId: string) {
    await markNotificationRead(notificationId);
    await query.refetch();
  }

  return (
    <div className="relative" ref={panelRef} data-testid="notification-bell">
      <IconButton
        aria-label={notificationCopy.bellLabel}
        aria-expanded={open}
        aria-controls={panelId}
        data-testid="notification-bell-button"
        onClick={() => setOpen((current) => !current)}
      >
        <Bell className="h-5 w-5" />
        {unreadCount > 0 ? (
          <span
            className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger-600 px-1 text-[10px] font-bold text-white"
            data-testid="notification-unread-count"
          >
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        ) : null}
      </IconButton>

      {open ? (
        <div
          id={panelId}
          role="region"
          aria-label={notificationCopy.panelTitle}
          className="absolute right-0 top-full z-dropdown mt-2 w-[min(100vw-2rem,22rem)] rounded-md border border-border bg-surface-raised p-3 shadow-lg"
          data-testid="notification-panel"
        >
          <p className="mb-2 text-small font-semibold uppercase tracking-wide text-text-secondary">
            {notificationCopy.panelTitle}
          </p>

          {query.isLoading ? (
            <div className="flex items-center gap-2 py-4 text-small text-text-secondary">
              <Spinner />
              <span>Đang tải…</span>
            </div>
          ) : null}

          {query.isError ? (
            <p className="py-2 text-small text-danger-600">{notificationCopy.loadError}</p>
          ) : null}

          {!query.isLoading && items.length === 0 ? (
            <p className="py-2 text-small text-text-secondary">{notificationCopy.empty}</p>
          ) : null}

          {items.length > 0 ? (
            <ul className="flex max-h-80 flex-col gap-2 overflow-y-auto">
              {items.map((item) => (
                <NotificationRow key={item.id} item={item} onRead={handleMarkRead} />
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
