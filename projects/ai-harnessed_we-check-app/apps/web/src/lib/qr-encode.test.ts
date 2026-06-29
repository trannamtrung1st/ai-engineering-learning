import { describe, expect, it } from "vitest";
import {
  createQrMatrix,
  QR_ENCODE_OPTIONS,
  QR_FULLSCREEN_SIZE,
  QR_PREVIEW_SIZE,
} from "@/lib/qr-encode";

/** NFR-20 — QR encoder parameters for projection readability */
describe("qr-encode (NFR-20)", () => {
  it("TC-NFR-20-002: uses error correction H and 4-module quiet zone", () => {
    const matrix = createQrMatrix(
      "wecheck://check-in?token=abc&session=def",
    );

    expect(QR_ENCODE_OPTIONS.errorCorrectionLevel).toBe("H");
    expect(QR_ENCODE_OPTIONS.margin).toBe(4);
    expect(matrix.modules.size).toBeGreaterThan(0);
  });

  it("defines preview and fullscreen pixel sizes per ui-ux §3.6", () => {
    expect(QR_PREVIEW_SIZE).toBeGreaterThanOrEqual(280);
    expect(QR_FULLSCREEN_SIZE).toBeGreaterThanOrEqual(480);
  });
});
