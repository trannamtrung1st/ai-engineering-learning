import { Card, CardContent } from "@/components/ui/card";
import { reportCopy } from "@/lib/copy/report-labels";

export interface ReportSummaryCardsProps {
  totalSessions?: number;
  avgAttendance?: string;
  totalAbsent?: number;
  totalExcused?: number;
}

/** FR-12 / AC-12 — filtered range summary stat cards */
export function ReportSummaryCards({
  totalSessions = 12,
  avgAttendance = "87%",
  totalAbsent = 24,
  totalExcused = 3,
}: ReportSummaryCardsProps) {
  const cards = [
    { label: reportCopy.summaryTotalSessions, value: String(totalSessions) },
    { label: reportCopy.summaryAvgAttendance, value: avgAttendance },
    { label: reportCopy.summaryTotalAbsent, value: String(totalAbsent) },
    { label: reportCopy.summaryTotalExcused, value: String(totalExcused) },
  ] as const;

  return (
    <div
      className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
      data-testid="report-summary-cards"
    >
      {cards.map((card) => (
        <Card key={card.label}>
          <CardContent className="pt-4">
            <p className="text-small text-text-secondary">{card.label}</p>
            <p className="text-h2 font-semibold text-text-primary">{card.value}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
