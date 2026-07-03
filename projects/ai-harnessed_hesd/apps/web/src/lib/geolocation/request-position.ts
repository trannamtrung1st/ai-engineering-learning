import type { GpsPayload } from "../api/check-in-api.js";

export type GeolocationResult =
  | { ok: true; gps: GpsPayload }
  | { ok: false; reason: "denied" | "unavailable" | "timeout" };

const GEO_TIMEOUT_MS = 12_000;

export function requestCurrentPosition(): Promise<GeolocationResult> {
  if (typeof navigator === "undefined" || !navigator.geolocation) {
    return Promise.resolve({ ok: false, reason: "unavailable" });
  }

  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        resolve({
          ok: true,
          gps: {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            accuracyMeters: position.coords.accuracy,
          },
        });
      },
      (error) => {
        if (error.code === error.PERMISSION_DENIED) {
          resolve({ ok: false, reason: "denied" });
          return;
        }
        resolve({ ok: false, reason: "unavailable" });
      },
      {
        enableHighAccuracy: true,
        timeout: GEO_TIMEOUT_MS,
        maximumAge: 0,
      },
    );
  });
}
