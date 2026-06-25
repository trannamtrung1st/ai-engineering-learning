import type { RegistrationState } from "@we-event/domain";

export interface RegistrationRow {
  id: string;
  eventId: string;
  participantId: string;
  state: RegistrationState;
  requestedAt: string;
  cancelledAt: string | null;
  statusReasonCode: string | null;
  statusReasonText: string | null;
  createdAt: string;
  updatedAt: string;
  version: number;
}

export interface WaitlistEntryRow {
  id: string;
  eventId: string;
  registrationId: string;
  position: number;
  enqueuedAt: string;
  promotedAt: string | null;
  expiredAt: string | null;
}

export interface RegistrationWithWaitlist extends RegistrationRow {
  waitlistPosition: number | null;
}

export interface RegisterInput {
  participantId: string;
}

export interface CancelInput {
  reasonCode?: string;
  reasonText?: string;
}

export interface ActorContext {
  actorId: string;
  actorRole: string;
}

export interface RegistrationAuditInput {
  eventId: string;
  registrationId: string;
  action: string;
  actorId: string;
  actorRole: string;
  reasonCode?: string | null;
  reasonText?: string | null;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
}
