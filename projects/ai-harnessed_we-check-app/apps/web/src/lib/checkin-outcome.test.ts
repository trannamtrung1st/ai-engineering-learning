import { describe, expect, it } from "vitest";
import {
  geoFailureToOutcome,
  formatDuplicateCheckInDetail,
  hasLocationConsent,
  markLocationConsent,
  resolveOutcomeAction,
  LOCATION_CONSENT_KEY,
} from "@/lib/checkin-outcome";
import { mapCheckInOutcome } from "@/lib/check-in-api";
import { getPermissionGuideContent } from "@/lib/copy/permission-guide";
import { parseCheckInQrPayload } from "@/lib/qr-deeplink";

/** AC-07, AC-08, AC-09, AC-10, BR-02, BR-03, BR-04, BR-11, BR-12, FR-07–FR-10, NFR-18, NFR-19 */
describe("checkin-outcome (AC-07, AC-08, AC-09, AC-10, BR-02, BR-03, BR-04, FR-07, NFR-19)", () => {
  it("maps API error codes to UI outcomes (BR-03 ExpiredQr, BR-04 DuplicateCheckIn)", () => {
    expect(mapCheckInOutcome("Success")).toBe("Present");
    expect(mapCheckInOutcome("ExpiredQr", "ExpiredQr")).toBe("ExpiredQr");
    expect(mapCheckInOutcome("DuplicateCheckIn", "DuplicateCheckIn")).toBe("DuplicateCheckIn");
    expect(mapCheckInOutcome("OutOfRadius", "OutOfRadius")).toBe("OutOfRadius");
    expect(mapCheckInOutcome("SpoofSuspected", "SpoofSuspected")).toBe("SpoofSuspected");
    expect(mapCheckInOutcome("GpsDisabled", "GpsDisabled")).toBe("GpsDisabled");
    expect(mapCheckInOutcome("TokenAlreadyUsed", "TokenAlreadyUsed")).toBe("TokenAlreadyUsed");
  });

  it("resolves outcome CTA actions per ui-states §4.3 (NFR-19)", () => {
    expect(resolveOutcomeAction("Present")).toBe("done");
    expect(resolveOutcomeAction("ExpiredQr")).toBe("scan_again");
    expect(resolveOutcomeAction("TokenAlreadyUsed")).toBe("scan_again");
    expect(resolveOutcomeAction("OutOfRadius")).toBe("retry_gps");
    expect(resolveOutcomeAction("GpsDisabled")).toBe("show_gps_guide");
    expect(resolveOutcomeAction("DuplicateCheckIn")).toBe("go_history");
    expect(resolveOutcomeAction("SpoofSuspected")).toBe("contact_instructor");
    expect(resolveOutcomeAction("NetworkError")).toBe("retry_gps");
  });

  it("maps GPS failures to GpsDisabled without server call (AC-08c, BR-12)", () => {
    expect(geoFailureToOutcome("denied")).toBe("GpsDisabled");
    expect(geoFailureToOutcome("timeout")).toBe("GpsDisabled");
  });

  it("parses wecheck QR deep link payloads (FR-07, NFR-18)", () => {
    const token = "40000000-0000-4000-8000-000000000401";
    const session = "30000000-0000-4000-8000-000000000301";
    expect(
      parseCheckInQrPayload(`wecheck://check-in?token=${token}&session=${session}`),
    ).toEqual({ tokenId: token, sessionId: session });
    expect(parseCheckInQrPayload(token)).toEqual({ tokenId: token });
  });

  it("provides distinct iOS and Android permission guide steps (NFR-19)", () => {
    const ios = getPermissionGuideContent("gps", "ios");
    const android = getPermissionGuideContent("gps", "android");
    expect(ios.steps.join(" ")).toMatch(/Safari/i);
    expect(android.steps.join(" ")).toMatch(/Chrome/i);
    expect(ios.steps).not.toEqual(android.steps);
  });

  it("formats duplicate check-in detail with prior timestamp (TC-AC-09-012)", () => {
    expect(formatDuplicateCheckInDetail()).toBe("Bạn đã điểm danh buổi học này rồi");
    expect(formatDuplicateCheckInDetail("2026-06-29T10:30:00.000Z")).toMatch(
      /Bạn đã điểm danh buổi học này rồi lúc/,
    );
  });

  it("persists location consent in localStorage (NFR-12)", () => {
    localStorage.removeItem(LOCATION_CONSENT_KEY);
    expect(hasLocationConsent()).toBe(false);
    markLocationConsent();
    expect(hasLocationConsent()).toBe(true);
    localStorage.removeItem(LOCATION_CONSENT_KEY);
  });
});
