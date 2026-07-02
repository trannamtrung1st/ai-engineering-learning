import { describe, expect, it } from "vitest";
import { ErrorCode } from "@attendly/domain";
import { loginRequiredMessage, resolveCheckInOutcomeCopy } from "./check-in-outcomes";

describe("check-in outcome i18n mapper (NFR-14)", () => {
  it("maps ExpiredQr to Vietnamese rescan guidance with retry", () => {
    const copy = resolveCheckInOutcomeCopy(ErrorCode.ExpiredQr);
    expect(copy.state).toBe("failure-expired-qr");
    expect(copy.title).toBe("Mã QR đã hết hạn");
    expect(copy.message).toContain("quét mã mới");
    expect(copy.retryAllowed).toBe(true);
  });

  it("maps GpsDisabled to Vietnamese location guidance", () => {
    const copy = resolveCheckInOutcomeCopy(ErrorCode.GpsDisabled);
    expect(copy.state).toBe("failure-gps-denied");
    expect(copy.title).toBe("Cần quyền vị trí");
    expect(copy.message).toContain("giảng viên hỗ trợ thủ công");
    expect(copy.retryAllowed).toBe(true);
  });

  it("maps OutOfRadius to Vietnamese out-of-radius guidance", () => {
    const copy = resolveCheckInOutcomeCopy(ErrorCode.OutOfRadius);
    expect(copy.state).toBe("failure-out-of-radius");
    expect(copy.title).toBe("Ngoài phạm vi lớp");
    expect(copy.message).toContain("phòng học");
    expect(copy.retryAllowed).toBe(true);
  });

  it("maps DuplicateCheckIn to info state without retry", () => {
    const copy = resolveCheckInOutcomeCopy(ErrorCode.DuplicateCheckIn);
    expect(copy.state).toBe("failure-duplicate");
    expect(copy.message).toContain("đã điểm danh");
    expect(copy.retryAllowed).toBe(false);
  });

  it("TC-AC-07-008: maps NotEnrolled without retry and admin guidance", () => {
    const copy = resolveCheckInOutcomeCopy(ErrorCode.NotEnrolled);
    expect(copy.state).toBe("failure-not-enrolled");
    expect(copy.message).toContain("Bạn không thuộc lớp học phần này");
    expect(copy.message).toContain("phòng đào tạo");
    expect(copy.retryAllowed).toBe(false);
  });

  it("exposes login-required message for auth gate", () => {
    expect(loginRequiredMessage()).toBe("Đăng nhập để tiếp tục");
  });
});
