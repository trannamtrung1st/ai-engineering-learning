import {
  markGpsSimOnceConsumed,
  readGpsCoordinateOverride,
  readGpsDelayOverride,
  readGpsSimMode,
  readGpsTimeoutOverride,
} from "@/lib/preview-sim";
import {
  isPreviewHarnessTokenId,
  PREVIEW_ROOM_GPS,
  resolvePreviewId,
} from "@/lib/preview-fixtures";

export interface GeoPosition {
  latitude: number;
  longitude: number;
  accuracyMeters: number;
}

export type GeoCaptureFailureReason = "denied" | "timeout" | "unavailable";

export type GeoCaptureResult =
  | { ok: true; position: GeoPosition }
  | { ok: false; reason: GeoCaptureFailureReason };

export const GPS_CAPTURE_TIMEOUT_MS = 15_000;
export const GPS_MAX_ATTEMPTS = 3;

function readPosition(position: GeolocationPosition): GeoPosition {
  return {
    latitude: position.coords.latitude,
    longitude: position.coords.longitude,
    accuracyMeters: position.coords.accuracy,
  };
}

function mapGeoError(error: { code: number }): GeoCaptureFailureReason {
  if (error.code === 1) return "denied";
  if (error.code === 3) return "timeout";
  return "unavailable";
}

function getCurrentPosition(timeoutMs: number): Promise<GeoPosition> {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("unavailable"));
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (position) => resolve(readPosition(position)),
      (error) => reject(error),
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 0 },
    );
  });
}

function simulateGpsCapture(
  mode: NonNullable<ReturnType<typeof readGpsSimMode>>,
  timeoutMs: number,
): Promise<GeoCaptureResult> {
  if (mode === "deny" || mode === "deny-once") {
    if (mode === "deny-once") {
      markGpsSimOnceConsumed();
    }
    return Promise.resolve({ ok: false, reason: "denied" });
  }

  if (mode === "unavailable") {
    return Promise.resolve({ ok: false, reason: "unavailable" });
  }

  if (mode === "hang" || mode === "timeout") {
    return new Promise((resolve) => {
      window.setTimeout(() => {
        resolve({ ok: false, reason: "timeout" });
      }, timeoutMs);
    });
  }

  if (mode === "delay") {
    return new Promise((resolve) => {
      window.setTimeout(() => {
        resolve({
          ok: true,
          position: {
            latitude: PREVIEW_ROOM_GPS.latitude,
            longitude: PREVIEW_ROOM_GPS.longitude,
            accuracyMeters: 12,
          },
        });
      }, timeoutMs);
    });
  }

  return Promise.resolve({ ok: false, reason: "unavailable" });
}

function readPreviewTokenDeepLink(): string | null {
  if (typeof window === "undefined") return null;
  const raw = new URLSearchParams(window.location.search).get("token");
  return resolvePreviewId(raw);
}

function resolvePreviewHarnessToken(
  tokenId?: string | null,
): string | null {
  const fromUrl = readPreviewTokenDeepLink();
  if (fromUrl && isPreviewHarnessTokenId(fromUrl)) return fromUrl;
  if (tokenId && isPreviewHarnessTokenId(tokenId)) return tokenId;
  return null;
}

/** AC-08c / BR-12 — single GPS attempt with 15 s timeout; UI handles retries */
export async function captureGeolocation(options?: {
  timeoutMs?: number;
  /** Scanned token from QR flow when URL has no ?token= (TC-FR-07-013). */
  tokenId?: string | null;
}): Promise<GeoCaptureResult> {
  const timeoutMs =
    options?.timeoutMs ?? readGpsTimeoutOverride() ?? GPS_CAPTURE_TIMEOUT_MS;

  const coordOverride = readGpsCoordinateOverride();
  if (coordOverride) {
    return {
      ok: true,
      position: {
        latitude: coordOverride.latitude,
        longitude: coordOverride.longitude,
        accuracyMeters: 12,
      },
    };
  }

  const simMode = readGpsSimMode();
  if (simMode) {
    return simulateGpsCapture(simMode, timeoutMs);
  }

  const previewToken = resolvePreviewHarnessToken(options?.tokenId);
  if (previewToken) {
    const delayMs = readGpsDelayOverride();
    if (delayMs && delayMs > 0) {
      await new Promise((resolve) => {
        window.setTimeout(resolve, delayMs);
      });
    }
    return {
      ok: true,
      position: {
        latitude: PREVIEW_ROOM_GPS.latitude,
        longitude: PREVIEW_ROOM_GPS.longitude,
        accuracyMeters: 12,
      },
    };
  }

  if (!navigator.geolocation) {
    return { ok: false, reason: "unavailable" };
  }

  try {
    const position = await getCurrentPosition(timeoutMs);
    return { ok: true, position };
  } catch (error) {
    if (typeof error === "object" && error !== null && "code" in error) {
      return { ok: false, reason: mapGeoError(error as { code: number }) };
    }
    return { ok: false, reason: "unavailable" };
  }
}
