import { describe, expect, it, beforeEach, afterEach } from "vitest";
import {
  markGpsSimOnceConsumed,
  readCameraSimMode,
  readGpsCoordinateOverride,
  readGpsSimMode,
  readGpsTimeoutOverride,
  readPlatformOverride,
  readUnsupportedBrowserOverride,
} from "@/lib/preview-sim";

/** NFR-18, NFR-19, BR-02, BR-12 — preview URL simulation hooks for browser gates */
describe("preview-sim (NFR-18, NFR-19, BR-02, BR-12)", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    sessionStorage.clear();
  });

  afterEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  function setSearch(search: string) {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, search },
    });
  }

  it("reads outside-radius GPS coordinates (TC-AC-08-016, BR-02)", () => {
    setSearch("?gpsLat=10.764122&gpsLng=106.660172");
    expect(readGpsCoordinateOverride()).toEqual({
      latitude: 10.764122,
      longitude: 106.660172,
    });
  });

  it("reads gpsSim timeout mode (TC-BR-12-013)", () => {
    setSearch("?gpsSim=timeout");
    expect(readGpsSimMode()).toBe("timeout");
    setSearch("?gpsSim=hang");
    expect(readGpsSimMode()).toBe("hang");
  });

  it("reads gpsTimeoutMs override for browser gates (TC-BR-12-013)", () => {
    setSearch("?gpsTimeoutMs=500");
    expect(readGpsTimeoutOverride()).toBe(500);
    setSearch("?gpsTimeoutMs=50");
    expect(readGpsTimeoutOverride()).toBeNull();
  });

  it("reads gpsSim deny-once then clears after consume (TC-BR-12-015)", () => {
    setSearch("?gpsSim=deny-once");
    expect(readGpsSimMode()).toBe("deny-once");
    markGpsSimOnceConsumed();
    expect(readGpsSimMode()).toBeNull();
  });

  it("reads platform override for permission guide (TC-NFR-19-011)", () => {
    setSearch("?platform=ios");
    expect(readPlatformOverride()).toBe("ios");
    setSearch("?platform=android");
    expect(readPlatformOverride()).toBe("android");
  });

  it("reads unsupported browser override (TC-NFR-18-017)", () => {
    setSearch("?unsupportedBrowser=1");
    expect(readUnsupportedBrowserOverride()).toBe(true);
    setSearch("?browserSim=ie");
    expect(readUnsupportedBrowserOverride()).toBe(true);
  });

  it("reads cameraSim deny (TC-NFR-19-007)", () => {
    setSearch("?cameraSim=deny");
    expect(readCameraSimMode()).toBe("deny");
  });
});
