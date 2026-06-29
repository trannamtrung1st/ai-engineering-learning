import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { rosterCopy } from "@/lib/copy/roster-labels";
import { fetchClasses, fetchSubjects, type ClassItem, type SubjectItem } from "@/lib/reference-api";

export interface RosterFilterSelection {
  classId: string;
  classCode: string;
  subjectId: string;
  subjectCode: string;
}

export interface RosterFilterBarProps {
  idPrefix?: string;
  initialClassCode?: string;
  initialSubjectCode?: string;
  autoApply?: boolean;
  onApply: (selection: RosterFilterSelection) => void;
  disabled?: boolean;
}

/** FR-03 / AC-03 — class + subject filter for roster listing */
export function RosterFilterBar({
  idPrefix = "roster",
  initialClassCode,
  initialSubjectCode,
  autoApply = false,
  onApply,
  disabled = false,
}: RosterFilterBarProps) {
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [subjects, setSubjects] = useState<SubjectItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [classId, setClassId] = useState("");
  const [subjectId, setSubjectId] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const [classItems, subjectItems] = await Promise.all([
          fetchClasses(),
          fetchSubjects(),
        ]);
        if (cancelled) return;
        setClasses(classItems);
        setSubjects(subjectItems);

        const initialClass =
          classItems.find((c) => c.code === initialClassCode) ?? classItems[0];
        const initialSubject =
          subjectItems.find((s) => s.code === initialSubjectCode) ?? subjectItems[0];

        if (initialClass) setClassId(initialClass.id);
        if (initialSubject) setSubjectId(initialSubject.id);

        if (autoApply && initialClass && initialSubject) {
          onApply({
            classId: initialClass.id,
            classCode: initialClass.code,
            subjectId: initialSubject.id,
            subjectCode: initialSubject.code,
          });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [initialClassCode, initialSubjectCode]);

  const selectedClass = classes.find((c) => c.id === classId);
  const selectedSubject = subjects.find((s) => s.id === subjectId);
  const canApply = !loading && !disabled && Boolean(selectedClass && selectedSubject);

  function handleApply() {
    if (!selectedClass || !selectedSubject) return;
    onApply({
      classId: selectedClass.id,
      classCode: selectedClass.code,
      subjectId: selectedSubject.id,
      subjectCode: selectedSubject.code,
    });
  }

  if (loading) {
    return (
      <div
        className="mb-4 flex flex-col gap-3 rounded-md border border-border bg-surface-raised p-4 lg:flex-row lg:items-end"
        data-testid="roster-filter-bar"
      >
        <Skeleton className="h-16 flex-1" />
        <Skeleton className="h-16 flex-1" />
        <Skeleton className="h-10 w-32" />
      </div>
    );
  }

  return (
    <div
      className="mb-4 flex flex-col gap-3 rounded-md border border-border bg-surface-raised p-4 lg:flex-row lg:items-end"
      data-testid="roster-filter-bar"
    >
      <div className="flex-1">
        <Label htmlFor={`${idPrefix}-class`}>{rosterCopy.filterClass}</Label>
        <select
          id={`${idPrefix}-class`}
          className="mt-1 flex min-h-touch w-full rounded-md border border-border bg-surface px-3 text-body"
          value={classId}
          onChange={(e) => setClassId(e.target.value)}
          disabled={disabled}
        >
          {classes.map((item) => (
            <option key={item.id} value={item.id}>
              {item.code} — {item.name}
            </option>
          ))}
        </select>
      </div>

      <div className="flex-1">
        <Label htmlFor={`${idPrefix}-subject`}>{rosterCopy.filterSubject}</Label>
        <select
          id={`${idPrefix}-subject`}
          className="mt-1 flex min-h-touch w-full rounded-md border border-border bg-surface px-3 text-body"
          value={subjectId}
          onChange={(e) => setSubjectId(e.target.value)}
          disabled={disabled}
        >
          {subjects.map((item) => (
            <option key={item.id} value={item.id}>
              {item.code} — {item.name}
            </option>
          ))}
        </select>
      </div>

      <Button type="button" disabled={!canApply} onClick={handleApply}>
        {rosterCopy.filterApply}
      </Button>
    </div>
  );
}
