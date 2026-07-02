import { useMemo } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { ErrorCode } from "@attendly/domain";
import { CheckInResultScreen } from "../../components/domain/CheckInResultScreen";
import { GpsPermissionPrompt } from "../../components/domain/GpsPermissionPrompt";
import { Button } from "../../components/ui/Button";
import { MobileFlowContainer } from "../../components/layout/MobileFlowContainer";
import {
  buildLoginRedirect,
  isStudentAuthenticated,
  preserveCheckInDeepLink,
  requiresCheckInAuth,
} from "../../lib/auth/auth-gate";
import { resolveCheckInOutcomeCopy } from "../../lib/i18n/check-in-outcomes";
import styles from "./StudentCheckInPage.module.css";

type OutcomePreview =
  | "form"
  | "expired-qr"
  | "gps-denied"
  | "out-of-radius"
  | "duplicate"
  | "success-present";

const outcomeCodeMap: Record<Exclude<OutcomePreview, "form">, string> = {
  "expired-qr": ErrorCode.ExpiredQr,
  "gps-denied": ErrorCode.GpsDisabled,
  "out-of-radius": ErrorCode.OutOfRadius,
  duplicate: ErrorCode.DuplicateCheckIn,
  "success-present": "Success",
};

export function StudentCheckInPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const outcome = (searchParams.get("outcome") as OutcomePreview | null) ?? "form";

  const copy = useMemo(() => {
    if (outcome === "form" || outcome === "success-present") {
      return null;
    }
    return resolveCheckInOutcomeCopy(outcomeCodeMap[outcome]);
  }, [outcome]);

  if (requiresCheckInAuth(searchParams) && !isStudentAuthenticated()) {
    const checkInPath = preserveCheckInDeepLink(
      "/check-in",
      `?${searchParams.toString()}`,
    );
    const { redirectTo } = buildLoginRedirect(checkInPath);
    return <Navigate to={redirectTo} replace />;
  }

  if (outcome === "success-present") {
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

  if (copy) {
    return (
      <MobileFlowContainer title="Điểm danh" subtitle="PG-02 · Kết quả">
        <CheckInResultScreen
          state={copy.state}
          title={copy.title}
          message={copy.message}
          retryAllowed={copy.retryAllowed}
          onRetry={() => setSearchParams({ outcome: "form" })}
          attendanceStatus={outcome === "duplicate" ? "Present" : undefined}
          timestamp={outcome === "duplicate" ? "08:02" : undefined}
        />
      </MobileFlowContainer>
    );
  }

  return (
    <MobileFlowContainer title="Điểm danh" subtitle="Quét mã QR từ giảng viên">
      <GpsPermissionPrompt
        onAllow={() => setSearchParams({ outcome: "success-present" })}
        onDeny={() => setSearchParams({ outcome: "gps-denied" })}
      />
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          setSearchParams({ outcome: "expired-qr" });
        }}
      >
        <Button type="submit" fullWidth size="lg">
          Xác nhận điểm danh
        </Button>
      </form>
    </MobileFlowContainer>
  );
}
