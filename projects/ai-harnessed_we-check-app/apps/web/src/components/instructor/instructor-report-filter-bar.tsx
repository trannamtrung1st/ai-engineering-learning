import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { reportCopy } from "@/lib/copy/report-labels";
import { defaultReportDateRange } from "@/lib/report-date-defaults";
import { fetchClasses, fetchSubjects, type ClassItem, type SubjectItem } from "@/lib/reference-api";
import type { ReportFilterParams } from "@/lib/reports-api";

export interface InstructorReportFilterBarProps {
  idPrefix?: string;
  initialFilters?: Partial<ReportFilterParams>;
  onApply: (filters: ReportFilterParams) => void;
  disabled?: boolean;
}

/** FR-12 / AC-12 / BR-08 — instructor-scoped report filters (assigned classes only) */
export function InstructorReportFilterBar({
  idPrefix = "instructor-report",
  initialFilters,
  onApply,
  disabled = false,
}: InstructorReportFilterBarProps) {
  const defaults = defaultReportDateRange();
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [subjects, setSubjects] = useState<SubjectItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [classCode, setClassCode] = useState(initialFilters?.classCode ?? "");
  const [subjectCode, setSubjectCode] = useState(initialFilters?.subjectCode ?? "");
  const [from, setFrom] = useState(initialFilters?.from ?? defaults.from);
  const [to, setTo] = useState(initialFilters?.to ?? defaults.to);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const [classItems, subjectItems] = await Promise.all([fetchClasses(), fetchSubjects()]);
        if (cancelled) return;
        setClasses(classItems);
        setSubjects(subjectItems);
        if (!classCode && classItems[0]) {
          setClassCode(classItems[0].code);
        }
        if (!subjectCode && subjectItems[0]) {
          setSubjectCode(subjectItems[0].code);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- seed defaults once on mount
  }, []);

  const canApply =
    !loading &&
    !disabled &&
    classCode.trim().length > 0 &&
    subjectCode.trim().length > 0 &&
    from.trim().length > 0 &&
    to.trim().length > 0;

  function handleApply() {
    if (!canApply) return;
    onApply({ classCode, subjectCode, from, to });
  }

  if (loading) {
    return (
      <div className="mb-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_1fr_1fr_auto]" data-testid="report-filter-bar">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }

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
          value={classCode}
          onChange={(e) => setClassCode(e.target.value)}
          disabled={disabled}
        >
          {classes.map((item) => (
            <option key={item.id} value={item.code}>
              {item.code}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="text-small font-medium" htmlFor={`${idPrefix}-subject`}>
          {reportCopy.filterSubject}
        </label>
        <select
          id={`${idPrefix}-subject`}
          className="mt-1 w-full rounded-md border border-border p-2"
          value={subjectCode}
          onChange={(e) => setSubjectCode(e.target.value)}
          disabled={disabled}
        >
          {subjects.map((item) => (
            <option key={item.id} value={item.code}>
              {item.code}
            </option>
          ))}
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
          value={from}
          onChange={(e) => setFrom(e.target.value)}
          disabled={disabled}
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
          value={to}
          onChange={(e) => setTo(e.target.value)}
          disabled={disabled}
        />
      </div>
      <div className="flex items-end">
        <Button type="button" disabled={!canApply} onClick={handleApply}>
          {reportCopy.filterApply}
        </Button>
      </div>
    </div>
  );
}
