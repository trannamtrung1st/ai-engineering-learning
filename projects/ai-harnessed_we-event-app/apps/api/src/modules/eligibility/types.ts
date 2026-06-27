import type {
  ActorRole,
  CertificateEligibilityState,
} from "@we-event/domain";

export interface ActorContext {
  actorId: string;
  actorRole: ActorRole;
}

export interface EligibilityRow {
  id: string;
  eventId: string;
  registrationId: string;
  participantId: string;
  result: CertificateEligibilityState;
  reasonCode: string | null;
  reasonText: string | null;
  evaluatedAt: string | null;
  overriddenBy: string | null;
  createdAt: string;
  updatedAt: string;
  version: number;
}

export interface EligibilityEvaluationResult {
  result: CertificateEligibilityState;
  reasonCode: string;
  reasonText: string;
}

export interface EligibilityListEntry {
  registrationId: string;
  participantId: string;
  registrationState: string;
  eligibility: ReturnType<typeof toEligibilityResponse>;
}

export interface ListEligibilityQuery {
  page?: string;
  pageSize?: string;
  sort?: string;
  eligibility?: string;
}

export interface ExportEventQuery {
  type?: string;
  eligibility?: string;
}

export interface RevokeEligibilityInput {
  reasonCode: string;
  reasonText: string;
}

export interface EligibilityAuditInput {
  eventId: string;
  eligibilityId: string;
  registrationId: string;
  action: string;
  actorId: string;
  actorRole: string;
  reasonCode?: string | null;
  reasonText?: string | null;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
}

export function toEligibilityResponse(row: EligibilityRow) {
  return {
    eligibilityId: row.id,
    eventId: row.eventId,
    registrationId: row.registrationId,
    participantId: row.participantId,
    result: row.result,
    reasonCode: row.reasonCode,
    reasonText: row.reasonText,
    evaluatedAt: row.evaluatedAt,
    overriddenBy: row.overriddenBy,
    updatedAt: row.updatedAt,
  };
}
