/** Format ISO-8601 check-in time for mobile PG-02 display (local HH:mm). */
export function formatCheckInTimestamp(iso: string, locale = "vi-VN"): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleTimeString(locale, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
