import { AttendanceStatus } from "@wecheck/domain";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AttendanceAuditEntry } from "@/lib/attendance-roster-api";
import {
  AttendanceAuditTrail,
  auditEntryMatches,
  mergeAuditEntriesWithOptimistic,
} from "@/components/domain/attendance/attendance-audit-trail";

vi.mock("@/lib/attendance-roster-api", () => ({
  fetchAttendanceAuditLogs: vi.fn(),
}));

import { fetchAttendanceAuditLogs } from "@/lib/attendance-roster-api";

const persistedEntry: AttendanceAuditEntry = {
  id: "audit-db-1",
  editorId: "instructor-1",
  editorDisplayName: "Giảng viên Nguyễn Văn B",
  previousStatus: AttendanceStatus.Absent,
  newStatus: AttendanceStatus.Present,
  note: "Xác minh trực tiếp tại lớp",
  editedAt: "2026-06-30T12:00:00.000Z",
};

const optimisticEntry: AttendanceAuditEntry = {
  id: "optimistic-rec-1-1719750000000",
  editorId: "instructor-1",
  editorDisplayName: "Giảng viên Nguyễn Văn B",
  previousStatus: AttendanceStatus.Absent,
  newStatus: AttendanceStatus.Present,
  note: "Xác minh trực tiếp tại lớp",
  editedAt: "2026-06-30T12:00:01.000Z",
};

describe("auditEntryMatches (NFR-15 / TC-NFR-15-015)", () => {
  it("matches optimistic and persisted rows on edit semantics, not id", () => {
    expect(auditEntryMatches(optimisticEntry, persistedEntry)).toBe(true);
  });

  it("does not match different status transitions", () => {
    expect(
      auditEntryMatches(optimisticEntry, {
        ...persistedEntry,
        newStatus: AttendanceStatus.Excused,
      }),
    ).toBe(false);
  });

  it("does not match when notes differ", () => {
    expect(
      auditEntryMatches(optimisticEntry, {
        ...persistedEntry,
        note: "Khác",
      }),
    ).toBe(false);
  });

  it("matches when optimistic note is null and persisted note is empty string", () => {
    expect(
      auditEntryMatches(
        { ...optimisticEntry, note: null },
        { ...persistedEntry, note: "" },
      ),
    ).toBe(true);
  });
});

describe("mergeAuditEntriesWithOptimistic (NFR-15 / TC-NFR-15-015)", () => {
  it("prepends optimistic entry when persisted data has not caught up", () => {
    expect(mergeAuditEntriesWithOptimistic([], optimisticEntry)).toEqual([optimisticEntry]);
  });

  it("collapses optimistic entry when persisted audit row matches semantics", () => {
    expect(mergeAuditEntriesWithOptimistic([persistedEntry], optimisticEntry)).toEqual([
      persistedEntry,
    ]);
  });
});

describe("AttendanceAuditTrail (NFR-15 / TC-NFR-15-015)", () => {
  beforeEach(() => {
    vi.mocked(fetchAttendanceAuditLogs).mockReset();
  });

  it("shows a single audit row after persisted data replaces optimistic duplicate", async () => {
    vi.mocked(fetchAttendanceAuditLogs).mockResolvedValue([persistedEntry]);

    render(
      <AttendanceAuditTrail recordId="rec-1" optimisticEntry={optimisticEntry} />,
    );

    fireEvent.click(screen.getByTestId("attendance-audit-trail-toggle"));

    await waitFor(() => {
      expect(screen.getByTestId("audit-entry-audit-db-1")).toBeInTheDocument();
    });

    expect(screen.queryByTestId(`audit-entry-${optimisticEntry.id}`)).not.toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText("Giảng viên Nguyễn Văn B")).toBeInTheDocument();
    expect(screen.getByTestId("audit-entry-note")).toHaveTextContent(
      "Xác minh trực tiếp tại lớp",
    );
  });

  it("acknowledges optimistic entry when persisted audit row matches semantics", async () => {
    const onAcknowledged = vi.fn();
    vi.mocked(fetchAttendanceAuditLogs).mockResolvedValue([persistedEntry]);

    render(
      <AttendanceAuditTrail
        recordId="rec-1"
        optimisticEntry={optimisticEntry}
        onOptimisticAcknowledged={onAcknowledged}
      />,
    );

    fireEvent.click(screen.getByTestId("attendance-audit-trail-toggle"));

    await waitFor(() => {
      expect(onAcknowledged).toHaveBeenCalledTimes(1);
    });
  });
});
