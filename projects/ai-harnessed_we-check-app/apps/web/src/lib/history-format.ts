/** vi-VN session date for history cards (AC-14, FR-14). */
export function formatHistorySessionDate(iso: string): string {
  return new Date(iso).toLocaleDateString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

/** vi-VN check-in time shown only on Present rows. */
export function formatHistoryCheckInTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}
