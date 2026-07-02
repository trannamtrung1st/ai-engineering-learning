import { beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorCode } from "@attendly/domain";
import {
  fetchSessionRoster,
  patchAttendanceCorrection,
} from "./roster-api";

describe("roster-api — FR-19 FR-20 AC-13 AC-14", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("TC-FR-19-003: fetchSessionRoster returns roster envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => ({
          data: {
            classSessionId: "70000000-0000-4000-8000-000000000002",
            state: "Open",
            counts: {
              present: 1,
              late: 0,
              pending: 2,
              absent: 0,
              excused: 0,
              manualPresent: 0,
              rejectedAttempts: 1,
            },
            rows: [
              {
                studentUserId: "60000000-0000-4000-8000-000000000002",
                studentCode: "SV001",
                displayName: "Trần Thị Sinh Viên",
                attendanceStatus: "Present",
                checkInMethod: "QR",
                checkInAt: "2026-07-02T08:05:00Z",
                latestAttemptOutcome: "Success",
              },
            ],
          },
          meta: { requestId: "req", timestamp: "2026-07-02T08:00:00Z" },
          error: null,
        }),
      }),
    );

    const result = await fetchSessionRoster("70000000-0000-4000-8000-000000000002");
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.roster.state).toBe("Open");
      expect(result.roster.counts.rejectedAttempts).toBe(1);
      expect(result.roster.rows[0]?.attendanceStatus).toBe("Present");
    }
  });

  it("TC-FR-20-005: patchAttendanceCorrection returns updated status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => ({
          data: {
            classSessionId: "70000000-0000-4000-8000-000000000002",
            studentUserId: "60000000-0000-4000-8000-000000000003",
            attendanceStatus: "Manual Present",
            checkInMethod: "Manual",
            checkInAt: "2026-07-02T09:00:00Z",
            previousStatus: "Absent",
            reason: "Sinh viên có mặt nhưng lỗi camera trên thiết bị.",
          },
          meta: { requestId: "req", timestamp: "2026-07-02T09:00:00Z" },
          error: null,
        }),
      }),
    );

    const result = await patchAttendanceCorrection(
      "70000000-0000-4000-8000-000000000002",
      "60000000-0000-4000-8000-000000000003",
      { status: "Manual Present", reason: "Sinh viên có mặt nhưng lỗi camera trên thiết bị." },
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data.attendanceStatus).toBe("Manual Present");
    }
  });

  it("TC-FR-20-012: patchAttendanceCorrection maps EditWindowExpired", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => ({
          data: null,
          meta: { requestId: "req", timestamp: "2026-07-02T09:00:00Z" },
          error: {
            code: ErrorCode.EditWindowExpired,
            message: "Hết thời gian chỉnh sửa.",
          },
        }),
      }),
    );

    const result = await patchAttendanceCorrection(
      "70000000-0000-4000-8000-000000000002",
      "60000000-0000-4000-8000-000000000003",
      { status: "Manual Present", reason: "Lý do hợp lệ đủ dài." },
    );
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.code).toBe(ErrorCode.EditWindowExpired);
      expect(result.status).toBe(409);
    }
  });
});
