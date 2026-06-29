/** Detect mobile platform for NFR-19 permission guide content */
export type MobilePlatform = "ios" | "android" | "unknown";

export function detectMobilePlatform(userAgent = navigator.userAgent): MobilePlatform {
  if (/iPhone|iPad|iPod/i.test(userAgent)) return "ios";
  if (/Android/i.test(userAgent)) return "android";
  return "unknown";
}

/** Resolve platform with optional URL override (?platform=ios|android). */
export function resolveMobilePlatform(
  userAgent = navigator.userAgent,
  platformOverride?: MobilePlatform | null,
): MobilePlatform {
  if (platformOverride === "ios" || platformOverride === "android") {
    return platformOverride;
  }
  return detectMobilePlatform(userAgent);
}
