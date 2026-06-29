import {
  markGpsSimOnceConsumed,
  readGpsCoordinateOverride,
  readGpsSimMode,
  readGpsTimeoutOverride,
} from "@/lib/preview-sim";

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

  return Promise.resolve({ ok: false, reason: "unavailable" });
}

/** AC-08c / BR-12 — single GPS attempt with 15 s timeout; UI handles retries */
export async function captureGeolocation(options?: {
  timeoutMs?: number;
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
