/** NFR-18 — detect supported mobile browsers for check-in */
export interface BrowserSupportResult {
  supported: boolean;
  reason?: "unsupported" | "missing-apis";
}

export function detectBrowserSupport(userAgent = navigator.userAgent): BrowserSupportResult {
  const hasGeolocation = typeof navigator.geolocation !== "undefined";

  if (/MSIE|Trident/i.test(userAgent)) {
    return { supported: false, reason: "unsupported" };
  }

  if (!hasGeolocation) {
    return { supported: false, reason: "missing-apis" };
  }

  const isIosSafari = /iPhone|iPad|iPod/i.test(userAgent) && /Safari/i.test(userAgent);
  const isAndroidChrome = /Android/i.test(userAgent) && /Chrome/i.test(userAgent);
  const isDesktopDev =
    /Chrome|Safari|Firefox|Edg/i.test(userAgent) &&
    !/MSIE|Trident/i.test(userAgent);

  if (isIosSafari || isAndroidChrome || isDesktopDev) {
    return { supported: true };
  }

  return { supported: false, reason: "unsupported" };
}

/** Resolve browser support with optional preview override (?unsupportedBrowser=1). */
export function resolveBrowserSupport(options?: {
  userAgent?: string;
  forceUnsupported?: boolean;
}): BrowserSupportResult {
  if (options?.forceUnsupported) {
    return { supported: false, reason: "unsupported" };
  }
  return detectBrowserSupport(options?.userAgent);
}
