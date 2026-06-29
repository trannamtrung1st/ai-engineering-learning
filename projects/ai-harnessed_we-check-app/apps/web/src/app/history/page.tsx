import { AttendanceHistoryList } from "@/components/student/attendance-history-list";

/** FR-14 / AC-14 — student attendance history page */
export function HistoryPage() {
  return (
    <div data-testid="history-page">
      <AttendanceHistoryList />
    </div>
  );
}
