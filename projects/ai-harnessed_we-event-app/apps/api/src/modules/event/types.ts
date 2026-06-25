import type { EventState } from "@we-event/domain";

export interface OrganizationRow {
  id: string;
  name: string;
}

export interface EventRuleConfigRow {
  eventId: string;
  capacity: number;
  waitlistEnabled: boolean;
  registrationOpenAt: string;
  registrationCloseAt: string;
  checkinOpenAt: string;
  checkinCloseAt: string;
  feedbackRequired: boolean;
  feedbackOpenAt: string;
  feedbackCloseAt: string;
  registrationPaused: boolean;
  version: number;
}

export interface EventRow {
  id: string;
  organizationId: string;
  name: string;
  description: string;
  location: string;
  state: EventState;
  startAt: string;
  endAt: string;
  createdBy: string;
  updatedBy: string;
  createdAt: string;
  updatedAt: string;
  version: number;
}

export interface EventWithConfig extends EventRow {
  ruleConfig: EventRuleConfigRow;
}

export interface CreateEventInput {
  organizationId?: string;
  name: string;
  description?: string;
  location?: string;
  startAt: string;
  endAt: string;
  ruleConfig: RuleConfigInput;
}

export interface RuleConfigInput {
  capacity: number;
  waitlistEnabled?: boolean;
  registrationOpenAt: string;
  registrationCloseAt: string;
  checkinOpenAt: string;
  checkinCloseAt: string;
  feedbackRequired?: boolean;
  feedbackOpenAt: string;
  feedbackCloseAt: string;
}

export interface UpdateEventInput {
  name?: string;
  description?: string;
  location?: string;
  startAt?: string;
  endAt?: string;
  ruleConfig?: Partial<RuleConfigInput> & {
    registrationPaused?: boolean;
  };
  reasonCode?: string;
  reasonText?: string;
}

export interface TransitionContext {
  actorId: string;
  actorRole: string;
  reasonCode?: string;
  reasonText?: string;
}

export interface ListEventsQuery {
  page?: string;
  pageSize?: string;
  q?: string;
  sort?: string;
  state?: string;
}

export interface EventListItem {
  eventId: string;
  name: string;
  state: EventState;
  startAt: string;
  location: string;
}
