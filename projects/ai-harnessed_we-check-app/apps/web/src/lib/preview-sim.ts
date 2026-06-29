import type { MobilePlatform } from "@/lib/detect-platform";

export type GpsSimMode = "deny" | "timeout" | "hang" | "delay" | "unavailable" | "deny-once";

const GPS_SIM_ONCE_KEY = "wecheck-gps-sim-once-consumed";

function readSearchParams(): URLSearchParams {
  if (typeof window === "undefined") return new URLSearchParams();
  return new URLSearchParams(window.location.search);
}

/** Preview-only GPS simulation for browser gates (BR-12, AC-08c). */
export function readGpsSimMode(): GpsSimMode | null {
  const sim = readSearchParams().get("gpsSim");
  if (
    sim === "deny" ||
    sim === "timeout" ||
    sim === "hang" ||
    sim === "delay" ||
    sim === "unavailable"
  ) {
    return sim;
  }
  if (sim === "deny-once") {
    try {
      if (sessionStorage.getItem(GPS_SIM_ONCE_KEY) === "1") return null;
    } catch {
      return "deny";
    }
    return "deny-once";
  }
  return null;
}

export function markGpsSimOnceConsumed(): void {
  try {
    sessionStorage.setItem(GPS_SIM_ONCE_KEY, "1");
  } catch {
    // ignore storage failures
  }
}

/** Fixed coordinates override — e.g. gpsLat=10.764122&gpsLng=106.660172 for OutOfRadius (BR-02). */
export function readGpsCoordinateOverride(): { latitude: number; longitude: number } | null {
  const latRaw = readSearchParams().get("gpsLat");
  const lngRaw = readSearchParams().get("gpsLng");
  if (!latRaw || !lngRaw) return null;

  const latitude = Number.parseFloat(latRaw);
  const longitude = Number.parseFloat(lngRaw);
  if (Number.isNaN(latitude) || Number.isNaN(longitude)) return null;
  return { latitude, longitude };
}

/** Platform override for permission guide content (NFR-19 TC-NFR-19-011). */
export function readPlatformOverride(): MobilePlatform | null {
  const platform = readSearchParams().get("platform");
  if (platform === "ios" || platform === "android") return platform;
  return null;
}

/** Force unsupported-browser gate without IE user agent (NFR-18 TC-NFR-18-017). */
export function readUnsupportedBrowserOverride(): boolean {
  const params = readSearchParams();
  return params.get("unsupportedBrowser") === "1" || params.get("browserSim") === "ie";
}

export type CameraSimMode = "deny" | "grant";

/** Force camera denial/grant for headless browser gates (NFR-19, NFR-18). */
export function readCameraSimMode(): CameraSimMode | null {
  const sim = readSearchParams().get("cameraSim");
  if (sim === "deny" || sim === "grant") return sim;
  return null;
}

/** Force QR scanner step even when ?token= is present (TC-FR-07-013, TC-NFR-19-016). */
export function readForceScannerEntry(): boolean {
  const params = readSearchParams();
  if (params.get("scannerOnly") === "1") return true;
  return readCameraSimMode() !== null;
}

/** Reset stored camera consent on entry for camera-consent browser gates (TC-NFR-19-020). */
export function readClearConsentOnEntry(): boolean {
  return readSearchParams().get("clearConsent") === "1";
}

/** Reset all stored consent flags — location + camera. */
export function readClearAllConsentOnEntry(): boolean {
  return readSearchParams().get("clearAllConsent") === "1";
}

/** Report mock-location in spoofMetadata for SpoofSuspected browser gates (AC-10, FR-10). */
export function readMockLocationDetected(): boolean {
  const params = readSearchParams();
  const raw = params.get("mockLocation") ?? params.get("mockLocationDetected");
  return raw === "1" || raw === "true";
}

/** Backdate auth session immediately before check-in submit (TC-AC-02-013). */
export function readExpireSessionOnSubmit(): boolean {
  const params = readSearchParams();
  return (
    params.get("expireSessionOnSubmit") === "1" ||
    params.get("previewExpireSession") === "1"
  );
}

/**
 * Optional delay before preview harness auto-resolves GPS on deep link (TC-BR-12-014).
 * e.g. gpsDelayMs=1500 keeps submit disabled with gps-required-badge during acquisition.
 */
export function readGpsDelayOverride(): number | null {
  const raw = readSearchParams().get("gpsDelayMs");
  if (!raw) return null;
  const parsed = Number.parseInt(raw, 10);
  if (Number.isNaN(parsed) || parsed < 0 || parsed > GPS_CAPTURE_TIMEOUT_MS) {
    return null;
  }
  return parsed;
}

/** Shorten GPS hang/timeout for browser gates — e.g. gpsTimeoutMs=500 (TC-BR-12-013). */
export function readGpsTimeoutOverride(): number | null {
  const raw = readSearchParams().get("gpsTimeoutMs");
  if (!raw) return null;
  const parsed = Number.parseInt(raw, 10);
  if (Number.isNaN(parsed) || parsed < 100 || parsed > GPS_CAPTURE_TIMEOUT_MS) {
    return null;
  }
  return parsed;
}

const GPS_CAPTURE_TIMEOUT_MS = 15_000;
