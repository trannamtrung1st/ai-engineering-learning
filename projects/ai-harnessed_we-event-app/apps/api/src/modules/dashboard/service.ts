import { ApiError } from "../../errors/api-error.js";
import { findEventById } from "../event/repository.js";
import { listRegistrationsForEligibilityPaginated } from "../eligibility/repository.js";
import {
  listRegistrationsForEvent,
  listWaitlistForEvent,
} from "../registration/repository.js";
import { countFeedbackSubmissionsForEvent } from "./repository.js";
import type { EventDashboardSummary } from "./types.js";

const LIST_OPTIONS = {
  sortColumn: "r.updated_at",
  sortDirection: "DESC" as const,
  limit: 1,
  offset: 0,
};

const WAITLIST_OPTIONS = {
  sortColumn: "w.position",
  sortDirection: "ASC" as const,
  limit: 1,
  offset: 0,
};

export class DashboardService {
  async getEventDashboard(eventId: string): Promise<EventDashboardSummary> {
    const event = await findEventById(eventId);
    if (!event) {
      throw new ApiError({
        code: "NOT_FOUND",
        message: "Event not found.",
        statusCode: 404,
        details: { eventId },
      });
    }

    const [
      registrations,
      registeredSeats,
      waitlist,
      checkedIn,
      attended,
      eligible,
      notEligible,
      pendingEligibility,
      feedbackSubmitted,
    ] = await Promise.all([
      listRegistrationsForEvent(eventId, LIST_OPTIONS),
      listRegistrationsForEvent(eventId, {
        ...LIST_OPTIONS,
        state: "Registered",
      }),
      listWaitlistForEvent(eventId, WAITLIST_OPTIONS),
      listRegistrationsForEvent(eventId, {
        ...LIST_OPTIONS,
        state: "CheckedIn",
      }),
      listRegistrationsForEvent(eventId, {
        ...LIST_OPTIONS,
        state: "Attended",
      }),
      listRegistrationsForEligibilityPaginated(eventId, {
        ...LIST_OPTIONS,
        eligibility: "Eligible",
      }),
      listRegistrationsForEligibilityPaginated(eventId, {
        ...LIST_OPTIONS,
        eligibility: "NotEligible",
      }),
      listRegistrationsForEligibilityPaginated(eventId, {
        ...LIST_OPTIONS,
        eligibility: "PendingEvaluation",
      }),
      countFeedbackSubmissionsForEvent(eventId),
    ]);

    return {
      eventId,
      capacity: event.ruleConfig.capacity,
      registrations: registrations.total,
      registeredSeats: registeredSeats.total,
      waitlist: waitlist.total,
      checkedIn: checkedIn.total,
      attended: attended.total,
      eligible: eligible.total,
      notEligible: notEligible.total,
      pendingEligibility: pendingEligibility.total,
      feedbackSubmitted,
      feedbackRequired: event.ruleConfig.feedbackRequired,
    };
  }
}

export const dashboardService = new DashboardService();
