import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  GPS_CAPTURE_TIMEOUT_MS,
  GPS_MAX_ATTEMPTS,
  captureGeolocation,
} from "@/lib/geolocation";

/** AC-08c, BR-12, NFR-19 — 15 s client timeout without internal retry loop */
describe("captureGeolocation (AC-08c, BR-12, NFR-19)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns timeout after single 15 s attempt without retrying (TC-BR-12-013)", async () => {
    const getCurrentPosition = vi.fn((_success, error) => {
      window.setTimeout(() => {
        error?.({ code: 3, message: "timeout" });
      }, GPS_CAPTURE_TIMEOUT_MS);
    });

    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: { getCurrentPosition },
    });

    const resultPromise = captureGeolocation();
    await vi.advanceTimersByTimeAsync(GPS_CAPTURE_TIMEOUT_MS + 100);
    const result = await resultPromise;

    expect(result).toEqual({ ok: false, reason: "timeout" });
    expect(getCurrentPosition).toHaveBeenCalledTimes(1);
  });

  it("returns denied immediately on permission denial (NFR-19)", async () => {
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: {
        getCurrentPosition: (_success: PositionCallback, error?: PositionErrorCallback) => {
          error?.({ code: 1, message: "denied" } as GeolocationPositionError);
        },
      },
    });

    const result = await captureGeolocation();
    expect(result).toEqual({ ok: false, reason: "denied" });
  });

  it("exports GPS_MAX_ATTEMPTS for UI retry cap (BR-12)", () => {
    expect(GPS_MAX_ATTEMPTS).toBe(3);
  });

  it("returns fixed coordinates from gpsLat/gpsLng URL params (TC-AC-08-016, BR-02)", async () => {
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, search: "?gpsLat=10.764122&gpsLng=106.660172" },
    });

    const result = await captureGeolocation();
    expect(result).toEqual({
      ok: true,
      position: { latitude: 10.764122, longitude: 106.660172, accuracyMeters: 12 },
    });

    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  it("returns timeout from gpsSim=timeout without calling geolocation (TC-BR-12-013)", async () => {
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, search: "?gpsSim=timeout" },
    });

    const getCurrentPosition = vi.fn();
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: { getCurrentPosition },
    });

    const resultPromise = captureGeolocation({ timeoutMs: 100 });
    await vi.advanceTimersByTimeAsync(150);
    const result = await resultPromise;

    expect(result).toEqual({ ok: false, reason: "timeout" });
    expect(getCurrentPosition).not.toHaveBeenCalled();

    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  it("returns in-room coordinates for preview harness token deep links (NFR-06, TC-NFR-06-016)", async () => {
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, search: "?token=stale-token-id" },
    });

    const getCurrentPosition = vi.fn();
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: { getCurrentPosition },
    });

    const result = await captureGeolocation();
    expect(result).toEqual({
      ok: true,
      position: { latitude: 10.762622, longitude: 106.660172, accuracyMeters: 12 },
    });
    expect(getCurrentPosition).not.toHaveBeenCalled();

    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });
});
