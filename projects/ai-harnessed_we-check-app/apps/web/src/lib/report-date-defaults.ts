/** Default report filter date range — start of current month through today (UTC dates). */
export function defaultReportDateRange(): { from: string; to: string } {
  const today = new Date();
  const from = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 1));
  const to = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
  return {
    from: from.toISOString().slice(0, 10),
    to: to.toISOString().slice(0, 10),
  };
}

export function formatReportDateVi(isoDate: string): string {
  const [year, month, day] = isoDate.slice(0, 10).split("-");
  if (!year || !month || !day) return isoDate;
  return `${day}/${month}/${year}`;
}

export function sessionDateInRange(
  scheduledStart: string,
  from: string,
  to: string,
): boolean {
  const sessionDate = scheduledStart.slice(0, 10);
  return sessionDate >= from && sessionDate <= to;
}

export function formatAttendanceRate(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}
