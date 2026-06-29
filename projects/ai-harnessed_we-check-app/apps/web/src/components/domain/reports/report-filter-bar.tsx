import { Button } from "@/components/ui/button";
import { reportCopy } from "@/lib/copy/report-labels";

export interface ReportFilterBarProps {
  showAllClasses?: boolean;
  idPrefix?: string;
}

/** FR-12 / AC-12 — shared report filter controls (instructor + admin) */
export function ReportFilterBar({
  showAllClasses = false,
  idPrefix = "report",
}: ReportFilterBarProps) {
  return (
    <div
      className="mb-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_1fr_1fr_auto]"
      data-testid="report-filter-bar"
    >
      <div>
        <label className="text-small font-medium" htmlFor={`${idPrefix}-class`}>
          {reportCopy.filterClass}
        </label>
        <select
          id={`${idPrefix}-class`}
          className="mt-1 w-full rounded-md border border-border p-2"
          defaultValue={showAllClasses ? "all" : "HESD-01"}
        >
          {showAllClasses ? (
            <option value="all">{reportCopy.filterAllClasses}</option>
          ) : null}
          <option value="HESD-01">HESD-01</option>
        </select>
      </div>
      <div>
        <label className="text-small font-medium" htmlFor={`${idPrefix}-subject`}>
          {reportCopy.filterSubject}
        </label>
        <select
          id={`${idPrefix}-subject`}
          className="mt-1 w-full rounded-md border border-border p-2"
          defaultValue="SWE-101"
        >
          <option value="SWE-101">SWE-101</option>
        </select>
      </div>
      <div>
        <label className="text-small font-medium" htmlFor={`${idPrefix}-from`}>
          {reportCopy.filterFromDate}
        </label>
        <input
          id={`${idPrefix}-from`}
          type="date"
          className="mt-1 w-full rounded-md border border-border p-2"
          defaultValue="2026-06-01"
        />
      </div>
      <div>
        <label className="text-small font-medium" htmlFor={`${idPrefix}-to`}>
          {reportCopy.filterToDate}
        </label>
        <input
          id={`${idPrefix}-to`}
          type="date"
          className="mt-1 w-full rounded-md border border-border p-2"
          defaultValue="2026-06-30"
        />
      </div>
      <div className="flex items-end">
        <Button type="button">{reportCopy.filterApply}</Button>
      </div>
    </div>
  );
}
