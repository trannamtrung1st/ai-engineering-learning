import type { MobilePlatform } from "@/lib/detect-platform";

export type GpsSimMode = "deny" | "timeout" | "hang" | "unavailable" | "deny-once";

const GPS_SIM_ONCE_KEY = "wecheck-gps-sim-once-consumed";

function readSearchParams(): URLSearchParams {
  if (typeof window === "undefined") return new URLSearchParams();
  return new URLSearchParams(window.location.search);
}

/** Preview-only GPS simulation for browser gates (BR-12, AC-08c). */
export function readGpsSimMode(): GpsSimMode | null {
  const sim = readSearchParams().get("gpsSim");
  if (sim === "deny" || sim === "timeout" || sim === "hang" || sim === "unavailable") {
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

/** Force camera denial for headless browser gates (NFR-19). */
export function readCameraSimMode(): "deny" | null {
  const sim = readSearchParams().get("cameraSim");
  return sim === "deny" ? "deny" : null;
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
