import { beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorCode } from "@attendly/domain";
import { submitCheckIn } from "./check-in-api";

describe("submitCheckIn (FR-16 FR-23)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("maps API success envelope to Present/Late result", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => ({
          data: {
            outcome: "Success",
            attendanceStatus: "Present",
            classSessionId: "session-1",
            checkInAt: "2026-07-02T08:02:11Z",
          },
          meta: { requestId: "req", timestamp: "2026-07-02T08:02:11Z" },
          error: null,
        }),
      }),
    );

    const result = await submitCheckIn({
      qrToken: "opaque",
      clientTimestamp: "2026-07-02T08:02:10Z",
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data.attendanceStatus).toBe("Present");
    }
  });

  it("maps rule-failure envelope to localized error code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => ({
          data: null,
          meta: { requestId: "req", timestamp: "2026-07-02T08:02:12Z" },
          error: {
            code: ErrorCode.ExpiredQr,
            message: "Mã QR đã hết hạn",
          },
        }),
      }),
    );

    const result = await submitCheckIn({
      qrToken: "expired",
      clientTimestamp: "2026-07-02T08:02:10Z",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.code).toBe(ErrorCode.ExpiredQr);
    }
  });

  it("maps DuplicateCheckIn envelope details for prior status display", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => ({
          data: null,
          meta: { requestId: "req", timestamp: "2026-07-02T08:02:12Z" },
          error: {
            code: ErrorCode.DuplicateCheckIn,
            message: "Bạn đã điểm danh buổi học này rồi.",
            details: {
              classSessionId: "session-1",
              attendanceStatus: "Present",
              checkInAt: "2026-07-02T08:02:11Z",
            },
          },
        }),
      }),
    );

    const result = await submitCheckIn({
      qrToken: "opaque",
      clientTimestamp: "2026-07-02T08:02:10Z",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.code).toBe(ErrorCode.DuplicateCheckIn);
      expect(result.details?.attendanceStatus).toBe("Present");
      expect(result.details?.checkInAt).toBe("2026-07-02T08:02:11Z");
    }
  });
});
