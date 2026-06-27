import {
  VALIDATION_ERROR_CODES,
  type CertificateEligibilityState,
} from "@we-event/domain";
import { ApiError } from "../../errors/api-error.js";
import type { EventWithConfig } from "../event/types.js";
import type { RegistrationRow } from "../registration/types.js";
import type { FeedbackRow } from "../feedback/types.js";
import type { EligibilityEvaluationResult, EligibilityRow } from "./types.js";

export const ELIGIBLE_REASON_CODE = "ELIGIBLE";
export const ELIGIBLE_REASON_TEXT =
  "Participant met all certificate eligibility requirements.";

/**
 * Deterministic eligibility evaluation order (BR-17, BR-18, BR-14):
 * 1. Attendance (Attended registration state)
 * 2. Mandatory feedback completion
 * 3. All rules pass
 */
export function evaluateEligibilityRules(
  registration: RegistrationRow,
  event: EventWithConfig,
  feedback: FeedbackRow | null,
): EligibilityEvaluationResult {
  if (registration.state !== "Attended") {
    return {
      result: "NotEligible",
      reasonCode: VALIDATION_ERROR_CODES.NOT_ELIGIBLE_ATTENDANCE,
      reasonText: "Participant did not attend the event.",
    };
  }

  if (event.ruleConfig.feedbackRequired && !feedback) {
    return {
      result: "NotEligible",
      reasonCode: VALIDATION_ERROR_CODES.NOT_ELIGIBLE_FEEDBACK,
      reasonText: "Mandatory feedback has not been submitted.",
    };
  }

  return {
    result: "Eligible",
    reasonCode: ELIGIBLE_REASON_CODE,
    reasonText: ELIGIBLE_REASON_TEXT,
  };
}

export function assertEvaluationHasReason(
  evaluation: EligibilityEvaluationResult,
): void {
  if (!evaluation.reasonCode?.trim() || !evaluation.reasonText?.trim()) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.ELIGIBILITY_REASON_MISSING,
      message: "Eligibility evaluation must include a reason.",
      statusCode: 500,
    });
  }
}

export function assertRevokeAllowed(
  row: EligibilityRow,
  actorRole: string,
  reasonCode?: string,
  reasonText?: string,
): void {
  if (actorRole !== "OrganizerAdmin") {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.ELIGIBILITY_OVERRIDE_FORBIDDEN,
      message: "Only organizer admins may revoke eligibility.",
      statusCode: 403,
    });
  }

  if (row.result !== "Eligible") {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.ELIGIBILITY_OVERRIDE_FORBIDDEN,
      message: "Only eligible participants may be revoked.",
      statusCode: 409,
      details: { currentResult: row.result },
    });
  }

  if (!reasonCode?.trim() || !reasonText?.trim()) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.ELIGIBILITY_OVERRIDE_FORBIDDEN,
      message: "A reason code and text are required to revoke eligibility.",
      statusCode: 400,
    });
  }
}

export function isTerminalEligibilityState(
  state: CertificateEligibilityState,
): boolean {
  return state === "Eligible" || state === "NotEligible" || state === "Revoked";
}
