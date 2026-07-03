import { beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorCode } from "@attendly/domain";
import {
  closeClassSession,
  fetchClassSessions,
  fetchCurrentQr,
  formatSessionLabel,
  openClassSession,
} from "./session-api";

describe("session-api (FR-07 FR-14 AC-01 AC-02)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("TC-FR-07-004: openClassSession maps Open envelope with QR preview", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => ({
          data: {
            classSessionId: "70000000-0000-4000-8000-000000000001",
            state: "Open",
            openedAt: "2026-07-02T08:00:00Z",
            qr: {
              expiresAt: "2026-07-02T08:00:30Z",
              qrPayload: "opaque-token",
            },
          },
          meta: { requestId: "req", timestamp: "2026-07-02T08:00:00Z" },
          error: null,
        }),
      }),
    );

    const result = await openClassSession("70000000-0000-4000-8000-000000000001");
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data.state).toBe("Open");
      expect(result.data.qr.qrPayload).toBe("opaque-token");
    }
  });

  it("TC-FR-07-007: openClassSession surfaces InvalidSessionTransition conflict", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => ({
          data: null,
          meta: { requestId: "req", timestamp: "2026-07-02T08:00:00Z" },
          error: {
            code: ErrorCode.InvalidSessionTransition,
            message: "Không thể thực hiện thao tác cho trạng thái hiện tại.",
            details: { fromState: "Closed" },
          },
        }),
      }),
    );

    const result = await openClassSession("70000000-0000-4000-8000-000000000002");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.code).toBe(ErrorCode.InvalidSessionTransition);
      expect(result.status).toBe(409);
    }
  });

  it("TC-AC-02-005: fetchCurrentQr returns Valid token metadata", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => ({
          data: {
            classSessionId: "70000000-0000-4000-8000-000000000002",
            tokenState: "Valid",
            expiresAt: "2026-07-02T08:00:30Z",
            qrPayload: "opaque-token",
          },
          meta: { requestId: "req", timestamp: "2026-07-02T08:00:00Z" },
          error: null,
        }),
      }),
    );

    const result = await fetchCurrentQr("70000000-0000-4000-8000-000000000002");
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.qr.tokenState).toBe("Valid");
      expect(result.qr.qrPayload).toBe("opaque-token");
    }
  });

  it("TC-FR-14-007: closeClassSession maps Closed summary envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => ({
          data: {
            classSessionId: "70000000-0000-4000-8000-000000000002",
            state: "Closed",
            closedAt: "2026-07-02T09:30:00Z",
            summary: { present: 2, late: 1, manualPresent: 0, absent: 1 },
          },
          meta: { requestId: "req", timestamp: "2026-07-02T09:30:00Z" },
          error: null,
        }),
      }),
    );

    const result = await closeClassSession("70000000-0000-4000-8000-000000000002");
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data.summary.absent).toBe(1);
    }
  });

  it("fetchClassSessions reads paginated list envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => ({
          data: [
            {
              classSessionId: "70000000-0000-4000-8000-000000000001",
              classSectionId: "50000000-0000-4000-8000-000000000001",
              sectionCode: "SE101-01",
              courseName: "Nhập môn phần mềm",
              roomCode: "A101",
              roomName: "Phòng A101",
              scheduledStartAt: "2026-07-03T08:00:00Z",
              scheduledEndAt: "2026-07-03T09:30:00Z",
              state: "Scheduled",
              openedAt: null,
              closedAt: null,
            },
          ],
          meta: {
            requestId: "req",
            timestamp: "2026-07-02T08:00:00Z",
            pagination: { page: 1, pageSize: 25, totalItems: 1, totalPages: 1 },
          },
          error: null,
        }),
      }),
    );

    const result = await fetchClassSessions({
      sortBy: "startTime",
      sortOrder: "desc",
      page: 1,
      pageSize: 25,
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.items).toHaveLength(1);
      expect(result.pagination.totalItems).toBe(1);
    }
  });

  it("formatSessionLabel combines course name and scheduled time", () => {
    const label = formatSessionLabel({
      courseName: "Nhập môn phần mềm",
      scheduledStartAt: "2026-07-03T08:00:00Z",
    });
    expect(label).toContain("Nhập môn phần mềm");
  });
});
