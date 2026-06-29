import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { CameraConsentBanner } from "@/components/domain/check-in/camera-consent-banner";
import { LocationConsentBanner } from "@/components/domain/check-in/location-consent-banner";
import { UnsupportedBrowserGate } from "@/components/domain/check-in/unsupported-browser-gate";
import { GpsCaptureStep, type GpsCaptureState } from "@/components/domain/check-in/gps-capture-step";
import { CheckInOutcomePanel } from "@/components/domain/check-in/check-in-outcome-panel";
import { QrScannerView } from "@/components/domain/check-in/qr-scanner-view";
import { PermissionGuideModal } from "@/components/shared/permission-guide-modal";
import { submitCheckInWithRetry } from "@/lib/check-in-api";
import { fetchAuthUser } from "@/lib/auth-session";
import {
  geoFailureToOutcome,
  hasCameraConsent,
  hasLocationConsent,
  markCameraConsent,
  markLocationConsent,
  resolveOutcomeAction,
} from "@/lib/checkin-outcome";
import type { CheckInOutcomeCode } from "@/lib/copy/checkin-messages";
import { authMessages } from "@/lib/copy/checkin-messages";
import { resolveBrowserSupport } from "@/lib/detect-browser-support";
import { resolveMobilePlatform } from "@/lib/detect-platform";
import { captureGeolocation, GPS_MAX_ATTEMPTS } from "@/lib/geolocation";
import { loginReturnUrl, resolvePreviewId } from "@/lib/preview-fixtures";
import {
  readPlatformOverride,
  readUnsupportedBrowserOverride,
} from "@/lib/preview-sim";
import { parseCheckInQrPayload } from "@/lib/qr-deeplink";
import type { PermissionGuideType } from "@/lib/copy/permission-guide";

type CheckInStep = "consent" | "camera_consent" | "scan" | "gps" | "outcome";

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

/** FR-07/FR-08 orchestrator: consent → scan → GPS → outcome (ui-states §4.1) */
export function CheckInFlow({ initialTokenId, previewOutcome }: CheckInFlowProps = {}) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const platformParam = searchParams.get("platform");
  const unsupportedBrowserParam = searchParams.get("unsupportedBrowser");
  const browserSimParam = searchParams.get("browserSim");
  const rawTokenParam = searchParams.get("token");
  const rawTokenId = initialTokenId ?? rawTokenParam;
  const tokenId = resolvePreviewId(rawTokenId);
  const sessionId = resolvePreviewId(searchParams.get("session"));
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

  const [step, setStep] = useState<CheckInStep>(() => {
    if (previewOutcome) return "outcome";
    if (tokenId) return hasLocationConsent() ? "gps" : "consent";
    if (hasLocationConsent()) return hasCameraConsent() ? "scan" : "camera_consent";
    return "consent";
  });
  const [showConsent, setShowConsent] = useState(() => !hasLocationConsent() && !previewOutcome);
  const [showCameraConsent, setShowCameraConsent] = useState(
    () => !tokenId && !hasCameraConsent() && !previewOutcome,
  );
  const [gpsState, setGpsState] = useState<GpsCaptureState>("requesting");
  const [gpsAttempt, setGpsAttempt] = useState(0);
  const [outcome, setOutcome] = useState<CheckInOutcomeCode>(previewOutcome ?? "Present");
  const [outcomeDetail, setOutcomeDetail] = useState<string | undefined>();
  const [permissionGuide, setPermissionGuide] = useState<PermissionGuideType | null>(null);
  const [scannedTokenId, setScannedTokenId] = useState<string | null>(tokenId);
  const autoGpsStarted = useRef(false);

  const activeTokenId = scannedTokenId ?? tokenId;

  const redirectToLogin = useCallback(
    (options?: { sessionExpired?: boolean }) => {
      const returnPath = buildReturnPath(rawTokenId, searchParams.get("session"));
      if (options?.sessionExpired) {
        toast.error(authMessages.sessionExpired, { id: "session-expired" });
        window.setTimeout(() => {
          window.location.href = loginReturnUrl(returnPath, options);
        }, 0);
        return;
      }
      window.location.href = loginReturnUrl(returnPath, options);
    },
    [rawTokenId, searchParams],
  );

  const ensureAuthenticated = useCallback(async (): Promise<boolean> => {
    const result = await fetchAuthUser();
    if (result.ok) return true;

    if (result.errorCode === "NetworkError") {
      setOutcome("NetworkError");
      setStep("outcome");
      return false;
    }

    redirectToLogin({ sessionExpired: result.errorCode === "SessionExpired" });
    return false;
  }, [redirectToLogin]);

  const submitToApi = useCallback(
    async (coords: { latitude: number; longitude: number; accuracyMeters?: number }) => {
      if (!activeTokenId) {
        setOutcome("Present");
        setStep("outcome");
        return;
      }

      if (!(await ensureAuthenticated())) return;

      setGpsState("submitting");
      try {
        const result = await submitCheckInWithRetry({
          tokenId: activeTokenId,
          latitude: coords.latitude,
          longitude: coords.longitude,
          spoofMetadata: {
            accuracyMeters: coords.accuracyMeters,
          },
        });

        if (result.requiresAuth) {
          redirectToLogin({ sessionExpired: result.sessionExpired });
          return;
        }

        setOutcome(result.outcome);
        setOutcomeDetail(result.message);
      } catch {
        setOutcome("NetworkError");
        setOutcomeDetail(undefined);
      } finally {
        setStep("outcome");
        setGpsState("requesting");
      }
    },
    [activeTokenId, ensureAuthenticated, redirectToLogin],
  );

  const runGpsCapture = useCallback(async () => {
    if (previewOutcome) {
      setOutcome(previewOutcome);
      setStep("outcome");
      return;
    }

    if (!(await ensureAuthenticated())) return;

    if (gpsAttempt >= GPS_MAX_ATTEMPTS) {
      setOutcome("GpsDisabled");
      setOutcomeDetail(undefined);
      setStep("outcome");
      return;
    }

    setGpsState("requesting");
    setGpsAttempt((attempt) => attempt + 1);

    await waitForGpsRequestingUi();

    const geo = await captureGeolocation();
    if (!geo.ok) {
      setGpsState("denied");
      setOutcome(geoFailureToOutcome(geo.reason));
      setOutcomeDetail(undefined);
      setStep("outcome");
      return;
    }

    setGpsState("acquiring");
    await submitToApi(geo.position);
  }, [ensureAuthenticated, gpsAttempt, previewOutcome, submitToApi]);

  useEffect(() => {
    if (
      tokenId &&
      step === "gps" &&
      !previewOutcome &&
      !autoGpsStarted.current &&
      gpsAttempt === 0
    ) {
      autoGpsStarted.current = true;
      void runGpsCapture();
    }
  }, [tokenId, step, previewOutcome, gpsAttempt, runGpsCapture]);

  const handleScan = useCallback(
    (payload: string) => {
      const parsed = parseCheckInQrPayload(payload);
      const nextToken = resolvePreviewId(parsed?.tokenId ?? payload) ?? parsed?.tokenId ?? null;
      if (!nextToken) return;

      setScannedTokenId(nextToken);
      setStep("gps");
      setGpsState("requesting");
      setGpsAttempt(0);
      void runGpsCapture();
    },
    [runGpsCapture],
  );

  const resetToScan = useCallback(() => {
    setScannedTokenId(null);
    autoGpsStarted.current = false;
    setOutcomeDetail(undefined);
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
    if (tokenId || scannedTokenId) {
      setStep("gps");
      setGpsAttempt(0);
      void runGpsCapture();
      return;
    }
    if (hasCameraConsent()) {
      setStep("scan");
    } else {
      setStep("camera_consent");
      setShowCameraConsent(true);
    }
  }, [runGpsCapture, scannedTokenId, tokenId]);

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
          cameraConsented={hasCameraConsent()}
        />
      ) : null}

      {step === "gps" ? (
        <>
          <GpsCaptureStep state={gpsState} attempt={gpsAttempt} />
          {gpsState === "requesting" || gpsState === "acquiring" ? (
            <ButtonRow
              label="Xác nhận điểm danh"
              onClick={() => void runGpsCapture()}
            />
          ) : null}
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
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className="mt-4 w-full min-h-touch rounded-md bg-primary-600 px-4 py-3 text-primary-foreground disabled:opacity-50"
      onClick={onClick}
      disabled={disabled}
      data-testid="check-in-submit"
    >
      {label}
    </button>
  );
}
