import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SessionStatus } from "@wecheck/domain";
import { useNavigate, useSearchParams } from "react-router-dom";
import { CameraConsentBanner } from "@/components/domain/check-in/camera-consent-banner";
import { LocationConsentBanner } from "@/components/domain/check-in/location-consent-banner";
import { UnsupportedBrowserGate } from "@/components/domain/check-in/unsupported-browser-gate";
import { GpsCaptureStep, type GpsCaptureState } from "@/components/domain/check-in/gps-capture-step";
import { CheckInOutcomePanel } from "@/components/domain/check-in/check-in-outcome-panel";
import { QrScannerView } from "@/components/domain/check-in/qr-scanner-view";
import { PermissionGuideModal } from "@/components/shared/permission-guide-modal";
import { submitCheckInWithRetry, fetchCheckInPreflight } from "@/lib/check-in-api";
import { fetchAuthUser } from "@/lib/auth-session";
import {
  CAMERA_CONSENT_KEY,
  LOCATION_CONSENT_KEY,
  geoFailureToOutcome,
  formatDuplicateCheckInDetail,
  hasCameraConsent,
  hasLocationConsent,
  markCameraConsent,
  markLocationConsent,
  resolveOutcomeAction,
} from "@/lib/checkin-outcome";
import type { CheckInOutcomeCode } from "@/lib/copy/checkin-messages";
import { resolveBrowserSupport } from "@/lib/detect-browser-support";
import { resolveMobilePlatform } from "@/lib/detect-platform";
import {
  captureGeolocation,
  GPS_MAX_ATTEMPTS,
  type GeoPosition,
} from "@/lib/geolocation";
import { loginReturnUrl, resolvePreviewId, PREVIEW_SESSION_IDS } from "@/lib/preview-fixtures";
import {
  readClearAllConsentOnEntry,
  readClearConsentOnEntry,
  readCameraSimMode,
  readExpireSessionOnSubmit,
  readForceScannerEntry,
  readMockLocationDetected,
  readPlatformOverride,
  readUnsupportedBrowserOverride,
} from "@/lib/preview-sim";
import { previewExpireSession } from "@/lib/session-monitor-api";
import { fetchSession } from "@/lib/sessions-api";
import { parseCheckInQrPayload } from "@/lib/qr-deeplink";
import type { PermissionGuideType } from "@/lib/copy/permission-guide";
import { appCopy } from "@/lib/copy/status-labels";

type CheckInStep = "consent" | "camera_consent" | "scan" | "preflight" | "gps" | "outcome";

type SessionGate = "idle" | "checking" | "open" | "closed";

/** Minimum time to show GPS requesting copy before preview auto-capture (NFR-17). */
const GPS_REQUESTING_MIN_DISPLAY_MS = 400;

function waitForGpsRequestingUi(): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, GPS_REQUESTING_MIN_DISPLAY_MS);
  });
}

export interface CheckInFlowProps {
  /** Override for tests — skip URL parsing */
  initialTokenId?: string | null;
  /** Force outcome preview without API */
  previewOutcome?: CheckInOutcomeCode | null;
}

function buildReturnPath(rawTokenId: string | null, sessionId: string | null): string {
  const params = new URLSearchParams();
  if (rawTokenId) params.set("token", rawTokenId);
  if (sessionId) params.set("session", sessionId);
  const query = params.toString();
  return query ? `/check-in?${query}` : "/check-in";
}

function clearPreviewConsentIfRequested(): void {
  try {
    if (readClearConsentOnEntry()) {
      localStorage.removeItem(CAMERA_CONSENT_KEY);
    }
    if (readClearAllConsentOnEntry()) {
      localStorage.removeItem(LOCATION_CONSENT_KEY);
      localStorage.removeItem(CAMERA_CONSENT_KEY);
    }
    if (readExpireSessionOnSubmit()) {
      markLocationConsent();
    }
  } catch {
    // ignore storage failures
  }
}

/** FR-07/FR-08 orchestrator: consent → scan → GPS → outcome (ui-states §4.1) */
export function CheckInFlow({ initialTokenId, previewOutcome }: CheckInFlowProps = {}) {
  const consentCleared = useRef(false);
  if (!consentCleared.current) {
    clearPreviewConsentIfRequested();
    consentCleared.current = true;
  }

  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const platformParam = searchParams.get("platform");
  const unsupportedBrowserParam = searchParams.get("unsupportedBrowser");
  const browserSimParam = searchParams.get("browserSim");
  const rawTokenParam = searchParams.get("token");
  const rawTokenId = initialTokenId ?? rawTokenParam;
  const resolvedTokenId = resolvePreviewId(rawTokenId);
  const forceScanner = readForceScannerEntry();
  const cameraSim = readCameraSimMode();
  const deepLinkTokenId = forceScanner ? null : resolvedTokenId;
  const sessionId = resolvePreviewId(searchParams.get("session"));
  const scannerCameraConsented = hasCameraConsent() || cameraSim !== null;

  const resolveInitialStep = (): CheckInStep => {
    if (previewOutcome) return "outcome";
    if (forceScanner) {
      if (readClearConsentOnEntry() && !hasCameraConsent()) return "camera_consent";
      return "scan";
    }
    // BR-15 — run token preflight before location consent (ExpiredQr needs no GPS)
    if (deepLinkTokenId) return "preflight";
    if (hasLocationConsent()) return hasCameraConsent() ? "scan" : "camera_consent";
    return "consent";
  };
  const platform = useMemo(
    () =>
      resolveMobilePlatform(
        undefined,
        platformParam === "ios" || platformParam === "android" ? platformParam : readPlatformOverride(),
      ),
    [platformParam],
  );
  const browserSupport = useMemo(
    () =>
      resolveBrowserSupport({
        forceUnsupported:
          unsupportedBrowserParam === "1" ||
          browserSimParam === "ie" ||
          readUnsupportedBrowserOverride(),
      }),
    [unsupportedBrowserParam, browserSimParam],
  );

  const [step, setStep] = useState<CheckInStep>(resolveInitialStep);
  const [showConsent, setShowConsent] = useState(
    () => !previewOutcome && !forceScanner && !deepLinkTokenId && !hasLocationConsent(),
  );
  const [showCameraConsent, setShowCameraConsent] = useState(() => {
    if (previewOutcome) return false;
    if (forceScanner) return readClearConsentOnEntry() && !hasCameraConsent();
    return !deepLinkTokenId && !hasCameraConsent();
  });
  const [gpsState, setGpsState] = useState<GpsCaptureState>("requesting");
  const [gpsAttempt, setGpsAttempt] = useState(0);
  const [capturedCoords, setCapturedCoords] = useState<GeoPosition | null>(null);
  const [outcome, setOutcome] = useState<CheckInOutcomeCode>(previewOutcome ?? "Present");
  const [outcomeDetail, setOutcomeDetail] = useState<string | undefined>();
  const [permissionGuide, setPermissionGuide] = useState<PermissionGuideType | null>(null);
  const [scannedTokenId, setScannedTokenId] = useState<string | null>(deepLinkTokenId);
  const [preflightPassed, setPreflightPassed] = useState(false);
  const preflightStarted = useRef(false);
  const autoGpsStarted = useRef(false);
  const sessionBlocked = useRef(false);
  const [sessionGate, setSessionGate] = useState<SessionGate>(() =>
    sessionId && !previewOutcome ? "checking" : "idle",
  );

  const activeTokenId = scannedTokenId ?? deepLinkTokenId;

  const redirectToLogin = useCallback(
    (options?: { sessionExpired?: boolean }) => {
      const returnPath = buildReturnPath(rawTokenId, searchParams.get("session"));
      window.location.href = loginReturnUrl(returnPath, options);
    },
    [rawTokenId, searchParams],
  );

  const ensureAuthenticated = useCallback(async (): Promise<boolean> => {
    const result = await fetchAuthUser();
    if (result.ok) {
      return true;
    }

    if (result.errorCode === "NetworkError") {
      setOutcome("NetworkError");
      setStep("outcome");
      return false;
    }

    redirectToLogin({ sessionExpired: result.errorCode === "SessionExpired" });
    return false;
  }, [redirectToLogin]);

  useEffect(() => {
    if (previewOutcome || !sessionId) {
      setSessionGate("idle");
      return;
    }

    if (sessionId === PREVIEW_SESSION_IDS.closed) {
      sessionBlocked.current = true;
      setSessionGate("closed");
      setOutcome("SessionNotActive");
      setStep("outcome");
      return;
    }

    let cancelled = false;
    setSessionGate("checking");
    void fetchSession(sessionId)
      .then((session) => {
        if (cancelled) return;
        if (session.status !== SessionStatus.Active) {
          sessionBlocked.current = true;
          setSessionGate("closed");
          setOutcome("SessionNotActive");
          setStep("outcome");
          return;
        }
        setSessionGate("open");
      })
      .catch(() => {
        if (!cancelled) {
          setSessionGate("open");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [previewOutcome, sessionId]);

  useEffect(() => {
    preflightStarted.current = false;
    setPreflightPassed(false);
  }, [rawTokenId, sessionId]);

  useEffect(() => {
    if (previewOutcome) return;
    void ensureAuthenticated();
  }, [ensureAuthenticated, previewOutcome, rawTokenId, sessionId]);

  const runPreflight = useCallback(
    async (tokenId: string) => {
      if (previewOutcome || sessionBlocked.current) return false;
      if (!(await ensureAuthenticated())) return false;

      const result = await fetchCheckInPreflight(tokenId, sessionId);
      if (result.ok) {
        setPreflightPassed(true);
        return true;
      }

      setOutcome(result.outcome);
      setOutcomeDetail(result.message);
      setStep("outcome");
      return false;
    },
    [ensureAuthenticated, previewOutcome, sessionId],
  );

  useEffect(() => {
    if (
      step !== "preflight" ||
      !activeTokenId ||
      preflightPassed ||
      preflightStarted.current ||
      previewOutcome ||
      sessionBlocked.current ||
      sessionGate === "checking" ||
      sessionGate === "closed"
    ) {
      return;
    }

    preflightStarted.current = true;
    void runPreflight(activeTokenId).then((passed) => {
      if (!passed) return;
      if (!hasLocationConsent()) {
        setStep("consent");
        setShowConsent(true);
        return;
      }
      setStep("gps");
      setGpsAttempt(0);
      autoGpsStarted.current = false;
    });
  }, [
    activeTokenId,
    preflightPassed,
    previewOutcome,
    runPreflight,
    sessionGate,
    step,
  ]);

  const submitToApi = useCallback(
    async (
      coords: { latitude: number; longitude: number; accuracyMeters?: number },
      tokenOverride?: string | null,
    ) => {
      if (sessionBlocked.current) return;

      const submitTokenId = tokenOverride ?? activeTokenId;
      if (!submitTokenId) {
        setOutcome("Present");
        setStep("outcome");
        return;
      }

      if (!(await ensureAuthenticated())) return;

      setGpsState("submitting");
      try {
        if (readExpireSessionOnSubmit()) {
          await previewExpireSession();
        }

        const result = await submitCheckInWithRetry({
          tokenId: submitTokenId,
          latitude: coords.latitude,
          longitude: coords.longitude,
          spoofMetadata: {
            accuracyMeters: coords.accuracyMeters,
            mockLocationDetected: readMockLocationDetected(),
          },
        });

        if (result.requiresAuth) {
          redirectToLogin({ sessionExpired: result.sessionExpired });
          return;
        }

        setOutcome(result.outcome);
        setOutcomeDetail(
          result.outcome === "DuplicateCheckIn"
            ? formatDuplicateCheckInDetail(result.priorCheckedInAt)
            : result.message,
        );
        setStep("outcome");
      } catch {
        setOutcome("NetworkError");
        setOutcomeDetail(undefined);
        setStep("outcome");
      } finally {
        setGpsState("requesting");
      }
    },
    [activeTokenId, ensureAuthenticated, redirectToLogin],
  );

  const runGpsCapture = useCallback(async (tokenOverride?: string | null) => {
    const captureTokenId = tokenOverride ?? activeTokenId;

    if (previewOutcome || sessionBlocked.current) {
      if (previewOutcome) {
        setOutcome(previewOutcome);
        setStep("outcome");
      }
      return;
    }

    if (!(await ensureAuthenticated())) return;

    if (gpsAttempt >= GPS_MAX_ATTEMPTS) {
      setOutcome("GpsDisabled");
      setOutcomeDetail(undefined);
      setStep("outcome");
      return;
    }

    setCapturedCoords(null);
    setGpsState("requesting");
    setGpsAttempt((attempt) => attempt + 1);

    await waitForGpsRequestingUi();

    const geo = await captureGeolocation({ tokenId: captureTokenId });
    if (!geo.ok) {
      setGpsState("denied");
      setOutcome(geoFailureToOutcome(geo.reason));
      setOutcomeDetail(undefined);
      setStep("outcome");
      return;
    }

    setCapturedCoords(geo.position);
    setGpsState("ready");
  }, [activeTokenId, ensureAuthenticated, gpsAttempt, previewOutcome]);

  const handleGpsSubmit = useCallback(
    (tokenOverride?: string | null) => {
      if (!capturedCoords) return;
      void submitToApi(capturedCoords, tokenOverride ?? activeTokenId);
    },
    [activeTokenId, capturedCoords, submitToApi],
  );

  useEffect(() => {
    if (
      step === "gps" &&
      preflightPassed &&
      (sessionGate === "open" || sessionGate === "idle") &&
      !previewOutcome &&
      !autoGpsStarted.current &&
      gpsAttempt === 0
    ) {
      autoGpsStarted.current = true;
      void runGpsCapture();
    }
  }, [
    step,
    preflightPassed,
    previewOutcome,
    gpsAttempt,
    runGpsCapture,
    sessionGate,
  ]);

  const handleScan = useCallback(
    (payload: string) => {
      const parsed = parseCheckInQrPayload(payload);
      const nextToken = resolvePreviewId(parsed?.tokenId ?? payload) ?? parsed?.tokenId ?? null;
      if (!nextToken) return;

      setScannedTokenId(nextToken);
      setPreflightPassed(false);
      preflightStarted.current = false;
      autoGpsStarted.current = false;
      setStep("preflight");
      setGpsState("requesting");
      setGpsAttempt(0);
    },
    [],
  );

  const resetToScan = useCallback(() => {
    setScannedTokenId(null);
    autoGpsStarted.current = false;
    preflightStarted.current = false;
    setPreflightPassed(false);
    setOutcomeDetail(undefined);
    setCapturedCoords(null);
    setStep(hasCameraConsent() ? "scan" : "camera_consent");
    setShowCameraConsent(!hasCameraConsent());
    setGpsState("requesting");
    setGpsAttempt(0);
    setOutcome("Present");
    navigate("/check-in", { replace: true });
  }, [navigate]);

  const handleOutcomeAction = useCallback(() => {
    const action = resolveOutcomeAction(outcome);

    switch (action) {
      case "show_gps_guide":
        setPermissionGuide("gps");
        return;
      case "show_camera_guide":
        setPermissionGuide("camera");
        return;
      case "go_history":
        navigate("/history");
        return;
      case "scan_again":
        resetToScan();
        return;
      case "retry_gps":
        setStep("gps");
        setGpsState("requesting");
        setGpsAttempt(0);
        setCapturedCoords(null);
        setOutcomeDetail(undefined);
        void runGpsCapture();
        return;
      case "done":
      case "close":
      case "contact_instructor":
        resetToScan();
        return;
      default:
        resetToScan();
    }
  }, [navigate, outcome, resetToScan, runGpsCapture]);

  const acceptConsent = useCallback(() => {
    markLocationConsent();
    setShowConsent(false);
    if ((deepLinkTokenId || scannedTokenId) && !readForceScannerEntry()) {
      setPreflightPassed(false);
      preflightStarted.current = false;
      setStep("preflight");
      setGpsAttempt(0);
      return;
    }
    if (hasCameraConsent()) {
      setStep("scan");
    } else {
      setStep("camera_consent");
      setShowCameraConsent(true);
    }
  }, [deepLinkTokenId, scannedTokenId]);

  const acceptCameraConsent = useCallback(() => {
    markCameraConsent();
    setShowCameraConsent(false);
    setStep("scan");
  }, []);

  if (!browserSupport.supported) {
    return (
      <div className="py-4" data-testid="check-in-flow">
        <UnsupportedBrowserGate />
      </div>
    );
  }

  return (
    <div className="py-4" data-testid="check-in-flow">
      {sessionId ? (
        <p className="mb-4 text-small text-text-secondary" data-testid="check-in-session-context">
          Buổi học: {sessionId.slice(0, 8)}…
        </p>
      ) : null}

      {showConsent && step === "consent" ? (
        <LocationConsentBanner onAccept={acceptConsent} />
      ) : null}

      {showCameraConsent && step === "camera_consent" ? (
        <CameraConsentBanner onAccept={acceptCameraConsent} />
      ) : null}

      {step === "scan" ? (
        <QrScannerView
          onScan={handleScan}
          onCameraDenied={() => setPermissionGuide("camera")}
          onOpenCameraGuide={() => setPermissionGuide("camera")}
          disabled={gpsState === "submitting"}
          cameraConsented={scannerCameraConsented}
        />
      ) : null}

      {step === "preflight" ? (
        <p
          className="py-8 text-center text-body text-text-secondary"
          data-testid="validating-token"
          aria-live="polite"
          aria-busy="true"
        >
          {appCopy.validatingQrToken}
        </p>
      ) : null}

      {step === "gps" ? (
        <>
          <GpsCaptureStep
            state={
              gpsState === "ready" || gpsState === "denied" || gpsState === "submitting"
                ? gpsState
                : sessionGate === "checking"
                  ? "requesting"
                  : gpsState
            }
            attempt={gpsAttempt}
          />
          <ButtonRow
            label="Xác nhận điểm danh"
            disabled={
              sessionGate === "checking" ||
              sessionGate === "closed" ||
              gpsState !== "ready" ||
              !capturedCoords
            }
            gpsRequired={sessionGate === "checking" || gpsState !== "ready"}
            onClick={() => handleGpsSubmit()}
          />
        </>
      ) : null}

      {step === "outcome" ? (
        <div aria-live="polite">
          <CheckInOutcomePanel
            outcome={outcome}
            detailMessage={outcomeDetail}
            onAction={handleOutcomeAction}
            onRetry={
              outcome === "GpsDisabled"
                ? () => {
                    setStep("gps");
                    setGpsState("requesting");
                    setOutcomeDetail(undefined);
                    void runGpsCapture();
                  }
                : undefined
            }
          />
        </div>
      ) : null}

      <PermissionGuideModal
        open={permissionGuide !== null}
        type={permissionGuide ?? "gps"}
        platform={platform}
        onClose={() => {
          setPermissionGuide(null);
          if (outcome === "GpsDisabled") {
            setStep("gps");
            setGpsState("requesting");
            setGpsAttempt(0);
            setOutcomeDetail(undefined);
            void runGpsCapture();
          }
        }}
      />
    </div>
  );
}

function ButtonRow({
  label,
  onClick,
  disabled,
  gpsRequired,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  gpsRequired?: boolean;
}) {
  return (
    <div className="mt-4 space-y-2">
      {gpsRequired ? (
        <p
          className="text-center text-small text-text-secondary"
          data-testid="gps-required-badge"
        >
          Cần bật GPS để điểm danh
        </p>
      ) : null}
      <button
        type="button"
        className="w-full min-h-touch rounded-md bg-primary-600 px-4 py-3 text-primary-foreground disabled:opacity-50"
        onClick={onClick}
        disabled={disabled}
        data-testid="check-in-submit"
        aria-disabled={disabled}
      >
        {label}
      </button>
    </div>
  );
}
