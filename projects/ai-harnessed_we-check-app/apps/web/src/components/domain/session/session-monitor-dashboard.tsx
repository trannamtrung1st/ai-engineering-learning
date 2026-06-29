import { Alert } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";
import { SpoofAlertBadge } from "@/components/domain/session/spoof-alert-badge";
import { useSessionMonitorPoll } from "@/hooks/use-session-monitor-poll";
import type { SessionMonitorRecord } from "@/lib/session-monitor-api";

export interface SessionMonitorDashboardProps {
  sessionId?: string;
  /** Fallback when API unavailable (storybook / offline) */
  showCodeSharingAlert?: boolean;
  showSpoofAlert?: boolean;
}

const statusLabels: Record<string, string> = {
  Present: "Có mặt",
  Pending: "Chưa điểm danh",
  Absent: "Vắng",
  Excused: "Có phép",
  Rejected: "Từ chối",
};

const statusColors: Record<string, string> = {
  Present: "text-success-700",
  Pending: "text-warning-700",
  Absent: "text-text-secondary",
  Excused: "text-primary-700",
  Rejected: "text-danger-700",
};

/** FR-15 / AC-10 / BR-11 — live attendance monitor with security alerts */
export function SessionMonitorDashboard({
  sessionId,
  showCodeSharingAlert = false,
  showSpoofAlert = false,
}: SessionMonitorDashboardProps) {
  const monitorQuery = useSessionMonitorPoll(sessionId, Boolean(sessionId));
  const data = monitorQuery.data;

  const summary = data?.summary ?? {
    present: showSpoofAlert ? 1 : 1,
    pending: 2,
    absent: 0,
    enrolled: 3,
    excused: 0,
    rejected: 0,
  };

  const codeSharingAlert = data?.alerts?.codeSharing ?? showCodeSharingAlert;
  const records: SessionMonitorRecord[] =
    data?.records ??
    (showSpoofAlert
      ? [
          {
            id: "preview-a",
            studentId: "a",
            institutionalId: "SV2026001",
            displayName: "Sinh viên Nguyễn Văn A",
            status: "Present",
            checkedInAt: null,
          },
          {
            id: "preview-b",
            studentId: "b",
            institutionalId: "SV2026002",
            displayName: "Sinh viên Trần Thị B",
            status: "Pending",
            checkedInAt: null,
            spoofSuspected: true,
          },
        ]
      : []);

  return (
    <div className="flex flex-col gap-4" data-testid="session-monitor-dashboard">
      {monitorQuery.isLoading && sessionId ? (
        <div className="flex items-center gap-2 text-small text-text-secondary">
          <Spinner className="h-4 w-4" />
          Đang tải dữ liệu buổi học…
        </div>
      ) : null}

      <div className="grid grid-cols-3 gap-3">
        <StatCard label="Có mặt" value={String(summary.present)} />
        <StatCard label="Chưa điểm danh" value={String(summary.pending)} />
        <StatCard label="Vắng" value={String(summary.absent)} />
      </div>

      {codeSharingAlert ? (
        <Alert variant="warning" title="Cảnh báo chia sẻ mã QR" data-testid="code-sharing-alert">
          Phát hiện thử sử dụng mã QR đã được quét. Yêu cầu sinh viên quét mã mới trên màn hình
          giảng viên.
        </Alert>
      ) : null}

      <table className="w-full text-left text-body">
        <thead>
          <tr className="border-b border-border text-small text-text-secondary">
            <th className="py-2">Sinh viên</th>
            <th className="py-2">Trạng thái</th>
            <th className="py-2">Ghi chú</th>
          </tr>
        </thead>
        <tbody>
          {records.length === 0 ? (
            <tr>
              <td colSpan={3} className="py-4 text-center text-text-secondary">
                Chưa có dữ liệu điểm danh
              </td>
            </tr>
          ) : (
            records.map((record) => (
              <tr
                key={record.id}
                className="border-b border-border"
                data-testid={`monitor-row-${record.institutionalId.toLowerCase()}`}
              >
                <td className="py-2">{record.displayName}</td>
                <td className={`py-2 ${statusColors[record.status] ?? ""}`}>
                  {statusLabels[record.status] ?? record.status}
                </td>
                <td className="py-2">
                  {record.spoofSuspected ? <SpoofAlertBadge /> : "—"}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-surface-raised p-3">
      <p className="text-small text-text-secondary">{label}</p>
      <p className="text-h2 font-semibold">{value}</p>
    </div>
  );
}
