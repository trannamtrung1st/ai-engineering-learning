import type { ActorRole } from "@we-event/domain";

export interface ActorContext {
  actorId: string;
  actorRole: ActorRole;
}

export interface FeedbackRow {
  id: string;
  eventId: string;
  registrationId: string;
  participantId: string;
  submittedAt: string;
  payload: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface SubmitFeedbackInput {
  registrationId?: string;
  answers: Record<string, unknown>;
}

export interface FeedbackAuditInput {
  eventId: string;
  registrationId: string;
  feedbackId: string;
  action: string;
  actorId: string;
  actorRole: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
}
