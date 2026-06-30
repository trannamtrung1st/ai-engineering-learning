import { History, QrCode } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import {
  CheckInOutcomePanel,
  CheckInOutcomeShowcase,
} from "@/components/domain/check-in/check-in-outcome-panel";
import { RoleHomeHub } from "@/components/layout/role-home-hub";
import { CheckInFlow } from "@/components/student/check-in-flow";
import type { CheckInOutcomeCode } from "@/lib/copy/checkin-messages";

const studentHubIcons = {
  "/check-in": QrCode,
  "/history": History,
} as const;

/** Student check-in route — NFR-17 Vietnamese copy, NFR-06 API-backed submission */
export function CheckInPage() {
  const [searchParams] = useSearchParams();
  const demoOutcomes = searchParams.get("demo") === "outcomes";
  const outcomeParam = searchParams.get("outcome") as CheckInOutcomeCode | null;
  const hasDeepLink = Boolean(searchParams.get("token") || searchParams.get("session"));
  const showStudentHub = !demoOutcomes && !outcomeParam && !hasDeepLink;

  if (demoOutcomes) {
    return (
      <div className="py-4">
        <CheckInOutcomeShowcase />
      </div>
    );
  }

  if (outcomeParam && !searchParams.get("token")) {
    return (
      <div className="py-4" data-testid="check-in-page">
        <CheckInOutcomePanel outcome={outcomeParam} />
      </div>
    );
  }

  return (
    <div data-testid="check-in-page">
      {showStudentHub ? (
        <RoleHomeHub variant="student" icons={studentHubIcons} className="mb-4" />
      ) : null}
      <CheckInFlow
        previewOutcome={
          outcomeParam && !searchParams.get("token") ? outcomeParam : undefined
        }
      />
    </div>
  );
}
