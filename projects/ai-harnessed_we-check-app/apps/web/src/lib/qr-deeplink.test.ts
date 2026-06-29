import { describe, expect, it } from "vitest";
import { parseCheckInQrPayload } from "@/lib/qr-deeplink";
import { PREVIEW_SESSION_IDS, PREVIEW_TOKEN_IDS } from "@/lib/preview-fixtures";

/** FR-07 — QR deep link parsing with preview aliases (TC-FR-07-013) */
describe("parseCheckInQrPayload (FR-07)", () => {
  it("parses wecheck URL with preview token alias (TC-FR-07-013)", () => {
    const result = parseCheckInQrPayload(
      `wecheck://check-in?token=valid-token-id&session=sess-1`,
    );
    expect(result).toEqual({
      tokenId: PREVIEW_TOKEN_IDS.valid,
      sessionId: PREVIEW_SESSION_IDS.active,
    });
  });

  it("parses bare preview token alias", () => {
    expect(parseCheckInQrPayload("valid-token-id")).toEqual({
      tokenId: PREVIEW_TOKEN_IDS.valid,
    });
  });

  it("parses UUID token directly", () => {
    expect(parseCheckInQrPayload(PREVIEW_TOKEN_IDS.stale)).toEqual({
      tokenId: PREVIEW_TOKEN_IDS.stale,
    });
  });
});
