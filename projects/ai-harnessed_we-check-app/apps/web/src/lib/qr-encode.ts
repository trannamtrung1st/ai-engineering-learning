import QRCode from "qrcode";

/** NFR-20 — preview minimum per event-specific-components §3.6 */
export const QR_PREVIEW_SIZE = 280;

/** NFR-20 — fullscreen presenter per event-specific-components §3.6 */
export const QR_FULLSCREEN_SIZE = 480;

export const QR_ENCODE_OPTIONS = {
  errorCorrectionLevel: "H" as const,
  margin: 4,
};

/** NFR-20 — high error correction + 4-module quiet zone for projection readability */
export async function encodeQrDataUrl(
  value: string,
  size: number,
): Promise<string> {
  return QRCode.toDataURL(value, {
    ...QR_ENCODE_OPTIONS,
    width: size,
    color: {
      dark: "#ffffff",
      light: "#00000000",
    },
  });
}

/** Sync matrix for unit tests verifying encoder parameters (NFR-20). */
export function createQrMatrix(value: string) {
  return QRCode.create(value, QR_ENCODE_OPTIONS);
}
