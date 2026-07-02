import { useCallback, useMemo, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { ErrorCode } from "@attendly/domain";
import { submitCheckIn } from "../../lib/api/check-in-api";
import { CheckInResultScreen } from "../../components/domain/CheckInResultScreen";
import type { AttendanceStatus } from "../../components/ui/StatusBadge";
import { GpsPermissionPrompt } from "../../components/domain/GpsPermissionPrompt";
import { Button } from "../../components/ui/Button";
import { FeedbackAlert } from "../../components/ui/FeedbackAlert";
import { MobileFlowContainer } from "../../components/layout/MobileFlowContainer";
import {
  buildLoginRedirect,
  isStudentAuthenticated,
  preserveCheckInDeepLink,
  requiresCheckInAuth,
} from "../../lib/auth/auth-gate";
import { formatCheckInTimestamp } from "../../lib/check-in/format-timestamp";
import { resolveDuplicatePriorStatus } from "../../lib/check-in/duplicate-prior-status";
import { resolveCheckInSuccessCopy } from "../../lib/check-in/success-copy";
import { requestCurrentPosition } from "../../lib/geolocation/request-position";
import { resolveCheckInOutcomeCopy } from "../../lib/i18n/check-in-outcomes";
import styles from "./StudentCheckInPage.module.css";

type OutcomePreview =
  | "form"
  | "expired-qr"
  | "gps-denied"
  | "out-of-radius"
  | "duplicate"
  | "not-enrolled"
  | "success-present"
  | "success-late";

const outcomeCodeMap: Record<Exclude<OutcomePreview, "form" | "success-present" | "success-late">, string> = {
  "expired-qr": ErrorCode.ExpiredQr,
  "gps-denied": ErrorCode.GpsDisabled,
  "out-of-radius": ErrorCode.OutOfRadius,
  duplicate: ErrorCode.DuplicateCheckIn,
  "not-enrolled": ErrorCode.NotEnrolled,
};

const PREVIEW_OUTCOMES = new Set<string>([
  "form",
  "expired-qr",
  "gps-denied",
  "out-of-radius",
  "duplicate",
  "not-enrolled",
  "success-present",
  "success-late",
]);

interface LiveResult {
  kind: "success";
  attendanceStatus: "Present" | "Late";
  timestamp: string;
}

interface LiveError {
  kind: "error";
  code: string;
  attendanceStatus?: AttendanceStatus;
  timestamp?: string;
}

function isPreviewMode(outcome: string | null): outcome is OutcomePreview {
  return outcome !== null && PREVIEW_OUTCOMES.has(outcome);
}

export function StudentCheckInPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const outcomeParam = searchParams.get("outcome");
  const qrToken = searchParams.get("token")?.trim() ?? "";
  const previewMode = isPreviewMode(outcomeParam);
  const outcome = (outcomeParam as OutcomePreview | null) ?? "form";

  const [submitting, setSubmitting] = useState(false);
  const [liveResult, setLiveResult] = useState<LiveResult | LiveError | null>(null);
  const [lastSuccess, setLastSuccess] = useState<LiveResult | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const previewCopy = useMemo(() => {
    if (
      !previewMode ||
      outcome === "form" ||
      outcome === "success-present" ||
      outcome === "success-late"
    ) {
      return null;
    }
    return resolveCheckInOutcomeCopy(outcomeCodeMap[outcome]);
  }, [outcome, previewMode]);

  const runCheckIn = useCallback(
    async (gps?: { latitude: number; longitude: number; accuracyMeters: number }) => {
      if (!qrToken) {
        setSubmitError("Thiếu mã QR. Vui lòng quét lại mã từ giảng viên.");
        return;
      }

      setSubmitting(true);
      setSubmitError(null);
      setLiveResult(null);

      try {
        const result = await submitCheckIn({
          qrToken,
          clientTimestamp: new Date().toISOString(),
          gps,
          idempotencyKey: crypto.randomUUID(),
        });

        if (result.ok) {
          const success: LiveResult = {
            kind: "success",
            attendanceStatus: result.data.attendanceStatus,
            timestamp: formatCheckInTimestamp(result.data.checkInAt),
          };
          setLastSuccess(success);
          setLiveResult(success);
          return;
        }

        const duplicatePrior =
          result.code === ErrorCode.DuplicateCheckIn
            ? (resolveDuplicatePriorStatus(result.details) ??
              (lastSuccess
                ? {
                    attendanceStatus: lastSuccess.attendanceStatus,
                    timestamp: lastSuccess.timestamp,
                  }
                : null))
            : null;

        setLiveResult({
          kind: "error",
          code: result.code,
          ...(duplicatePrior
            ? {
                attendanceStatus: duplicatePrior.attendanceStatus,
                timestamp: duplicatePrior.timestamp,
              }
            : {}),
        });
      } catch {
        setSubmitError("Không thể kết nối máy chủ. Vui lòng thử lại.");
      } finally {
        setSubmitting(false);
      }
    },
    [qrToken, lastSuccess],
  );

  const handleRetry = useCallback(() => {
    setLiveResult(null);
    setSubmitError(null);
    const next = new URLSearchParams(searchParams);
    next.delete("outcome");
    setSearchParams(next);
  }, [searchParams, setSearchParams]);

  if (!previewMode && requiresCheckInAuth(searchParams) && !isStudentAuthenticated()) {
    const checkInPath = preserveCheckInDeepLink("/check-in", `?${searchParams.toString()}`);
    const { redirectTo } = buildLoginRedirect(checkInPath);
    return <Navigate to={redirectTo} replace />;
  }

  if (previewMode && outcome === "success-present") {
    return (
      <MobileFlowContainer title="Điểm danh" subtitle="PG-02 · Kết quả">
        <CheckInResultScreen
          state="success-present"
          title="Điểm danh thành công — Có mặt"
          message="Bạn đã điểm danh thành công cho buổi học này."
          attendanceStatus="Present"
          timestamp="08:02"
        />
      </MobileFlowContainer>
    );
  }

  if (previewMode && outcome === "success-late") {
    return (
      <MobileFlowContainer title="Điểm danh" subtitle="PG-02 · Kết quả">
        <CheckInResultScreen
          state="success-late"
          title="Điểm danh thành công — Đi trễ"
          message="Bạn đã điểm danh thành công cho buổi học này (trễ)."
          attendanceStatus="Late"
          timestamp="08:17"
        />
      </MobileFlowContainer>
    );
  }

  if (previewMode && previewCopy) {
    return (
      <MobileFlowContainer title="Điểm danh" subtitle="PG-02 · Kết quả">
        <CheckInResultScreen
          state={previewCopy.state}
          title={previewCopy.title}
          message={previewCopy.message}
          retryAllowed={previewCopy.retryAllowed}
          onRetry={() => setSearchParams({ outcome: "form" })}
          attendanceStatus={outcome === "duplicate" ? "Present" : undefined}
          timestamp={outcome === "duplicate" ? "08:02" : undefined}
        />
      </MobileFlowContainer>
    );
  }

  if (liveResult?.kind === "success") {
    const copy = resolveCheckInSuccessCopy(liveResult.attendanceStatus);
    return (
      <MobileFlowContainer title="Điểm danh" subtitle="PG-02 · Kết quả">
        <CheckInResultScreen
          state={copy.state}
          title={copy.title}
          message={copy.message}
          attendanceStatus={liveResult.attendanceStatus}
          timestamp={liveResult.timestamp}
        />
      </MobileFlowContainer>
    );
  }

  if (liveResult?.kind === "error") {
    const copy = resolveCheckInOutcomeCopy(liveResult.code);
    return (
      <MobileFlowContainer title="Điểm danh" subtitle="PG-02 · Kết quả">
        <CheckInResultScreen
          state={copy.state}
          title={copy.title}
          message={copy.message}
          retryAllowed={copy.retryAllowed}
          onRetry={handleRetry}
          attendanceStatus={liveResult.attendanceStatus}
          timestamp={liveResult.timestamp}
        />
      </MobileFlowContainer>
    );
  }

  return (
    <MobileFlowContainer title="Điểm danh" subtitle="Quét mã QR từ giảng viên">
      {!qrToken ? (
        <FeedbackAlert variant="brand" title="Quét mã QR để bắt đầu">
          Mở camera điện thoại và quét mã QR trên màn hình giảng viên. Liên kết sẽ mở trang điểm
          danh với mã phiên học.
        </FeedbackAlert>
      ) : null}

      {submitError ? (
        <FeedbackAlert variant="danger" title="Không thể điểm danh">
          {submitError}
        </FeedbackAlert>
      ) : null}

      <GpsPermissionPrompt
        onAllow={async () => {
          if (previewMode) {
            setSearchParams({ outcome: "success-present" });
            return;
          }
          const position = await requestCurrentPosition();
          if (!position.ok) {
            await runCheckIn();
            return;
          }
          await runCheckIn(position.gps);
        }}
        onDeny={() => {
          if (previewMode) {
            setSearchParams({ outcome: "gps-denied" });
            return;
          }
          void runCheckIn();
        }}
      />
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          if (previewMode) {
            setSearchParams({ outcome: "expired-qr" });
            return;
          }
          void runCheckIn();
        }}
      >
        <Button type="submit" fullWidth size="lg" disabled={submitting || !qrToken}>
          {submitting ? "Đang điểm danh…" : "Xác nhận điểm danh"}
        </Button>
      </form>
    </MobileFlowContainer>
  );
}
