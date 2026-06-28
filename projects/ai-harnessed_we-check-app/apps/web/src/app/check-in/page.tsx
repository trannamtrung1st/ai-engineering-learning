import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { LocationConsentBanner } from "@/components/domain/check-in/location-consent-banner";
import { GpsCaptureStep } from "@/components/domain/check-in/gps-capture-step";
import {
  CheckInOutcomePanel,
  CheckInOutcomeShowcase,
} from "@/components/domain/check-in/check-in-outcome-panel";
import { QrScannerView } from "@/components/domain/check-in/qr-scanner-view";
import { submitCheckIn } from "@/lib/check-in-api";
import { isAuthenticated } from "@/lib/auth-session";
import { loginReturnUrl, resolvePreviewId } from "@/lib/preview-fixtures";
import type { CheckInOutcomeCode } from "@/lib/copy/checkin-messages";

type CheckInStep = "consent" | "scan" | "gps" | "outcome";

/** Default in-room coordinates for shell check-in API submission */
const DEFAULT_CHECKIN_COORDS = { latitude: 10.762622, longitude: 106.660172 };

/** Student check-in shell page — NFR-17 Vietnamese copy, NFR-06 API-backed submission */
export function CheckInPage() {
  const [searchParams] = useSearchParams();
  const demoOutcomes = searchParams.get("demo") === "outcomes";
  const outcomeParam = searchParams.get("outcome") as CheckInOutcomeCode | null;
  const rawTokenId = searchParams.get("token");
  const tokenId = resolvePreviewId(rawTokenId);
  const hasToken = Boolean(tokenId);

  const [step, setStep] = useState<CheckInStep>(hasToken ? "gps" : "consent");
  const [showConsent, setShowConsent] = useState(!hasToken);
  const [gpsState, setGpsState] = useState<"requesting" | "submitting">("requesting");
  const [outcome, setOutcome] = useState<CheckInOutcomeCode>(
    outcomeParam ?? "Present",
  );

  const handleScan = useCallback(() => {
    setStep("gps");
  }, []);

  const submitToApi = useCallback(async () => {
    if (!tokenId) {
      setOutcome("Present");
      setStep("outcome");
      return;
    }

    const authed = await isAuthenticated();
    if (!authed) {
      const returnPath = `/check-in?token=${encodeURIComponent(rawTokenId ?? tokenId ?? "")}`;
      window.location.href = loginReturnUrl(returnPath);
      return;
    }

    setGpsState("submitting");
    try {
      const result = await submitCheckIn({
        tokenId,
        ...DEFAULT_CHECKIN_COORDS,
      });
      if (result.requiresAuth) {
        const returnPath = `/check-in?token=${encodeURIComponent(rawTokenId ?? tokenId ?? "")}`;
        window.location.href = loginReturnUrl(returnPath, {
          sessionExpired: result.sessionExpired,
        });
        return;
      }
      setOutcome(result.outcome);
    } catch {
      setOutcome("NetworkError");
    } finally {
      setStep("outcome");
    }
  }, [tokenId, rawTokenId]);

  const handleGpsComplete = useCallback(() => {
    if (outcomeParam) {
      setStep("outcome");
      setOutcome(outcomeParam);
      return;
    }
    void submitToApi();
  }, [outcomeParam, submitToApi]);

  useEffect(() => {
    if (hasToken && step === "gps" && !outcomeParam && gpsState === "requesting") {
      const timer = window.setTimeout(handleGpsComplete, 1500);
      return () => window.clearTimeout(timer);
    }
  }, [hasToken, step, outcomeParam, gpsState, handleGpsComplete]);

  if (demoOutcomes) {
    return (
      <div className="py-4">
        <CheckInOutcomeShowcase />
      </div>
    );
  }

  if (outcomeParam && !hasToken) {
    return (
      <div className="py-4">
        <CheckInOutcomePanel outcome={outcomeParam} onAction={() => setStep("scan")} />
      </div>
    );
  }

  return (
    <div className="py-4" data-testid="check-in-page">
      {showConsent && step === "consent" ? (
        <LocationConsentBanner
          onAccept={() => {
            setShowConsent(false);
            setStep("scan");
          }}
        />
      ) : null}

      {step === "scan" ? <QrScannerView onScan={handleScan} /> : null}

      {step === "gps" ? (
        <>
          <GpsCaptureStep state={gpsState} />
          {gpsState === "requesting" ? (
            <button
              type="button"
              className="mt-4 w-full rounded-md bg-primary-600 px-4 py-3 text-primary-foreground"
              onClick={handleGpsComplete}
            >
              Hoàn tất xác minh vị trí
            </button>
          ) : null}
        </>
      ) : null}

      {step === "outcome" ? (
        <CheckInOutcomePanel
          outcome={outcome}
          onAction={() => {
            setStep("scan");
            setGpsState("requesting");
          }}
        />
      ) : null}
    </div>
  );
}
