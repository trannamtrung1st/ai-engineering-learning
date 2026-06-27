import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildEventDashboardKpiItems,
  feedbackCompletionRatio,
} from "./event-dashboard-kpis.js";
import type { EventDashboardMetrics } from "./organizer-api.js";

const LINKS = {
  registrations: "/organizer/events/e1/registrations",
  waitlist: "/organizer/events/e1/waitlist",
  checkIn: "/organizer/events/e1/check-in",
  eligibility: "/organizer/events/e1/eligibility",
};

function metrics(
  overrides: Partial<EventDashboardMetrics> = {},
): EventDashboardMetrics {
  return {
    registrations: 10,
    registeredSeats: 8,
    waitlist: 2,
    checkedIn: 3,
    attended: 4,
    eligible: 2,
    notEligible: 1,
    pendingEligibility: 1,
    feedbackSubmitted: 2,
    feedbackRequired: true,
    mandatoryFeedbackOutstanding: 2,
    ...overrides,
  };
}

describe("event-dashboard-kpis (FR-22)", () => {
  it("builds five KPI blocks with drill-down links (TC-FR-22-009)", () => {
    const items = buildEventDashboardKpiItems(metrics(), LINKS);

    assert.equal(items.length, 5);
    assert.equal(items[0]?.label, "Registrations");
    assert.equal(items[0]?.href, LINKS.registrations);
    assert.equal(items[1]?.href, LINKS.waitlist);
    assert.equal(items[2]?.href, LINKS.checkIn);
    assert.equal(items[3]?.label, "Feedback");
    assert.match(String(items[3]?.hint), /mandatory outstanding/);
    assert.equal(items[4]?.href, LINKS.eligibility);
  });

  it("surfaces mandatory feedback outstanding when policy is required (TC-FR-22-006)", () => {
    const items = buildEventDashboardKpiItems(
      metrics({ mandatoryFeedbackOutstanding: 3 }),
      LINKS,
    );
    const feedback = items.find((item) => item.label === "Feedback");

    assert.match(String(feedback?.hint), /3 mandatory outstanding/);
  });

  it("shows optional feedback copy when feedbackRequired is false (TC-FR-22-015)", () => {
    const items = buildEventDashboardKpiItems(
      metrics({ feedbackRequired: false, mandatoryFeedbackOutstanding: 0 }),
      LINKS,
    );
    const feedback = items.find((item) => item.label === "Feedback");

    assert.match(String(feedback?.hint), /optional/);
  });

  it("computes feedback completion ratio from attended denominator (FR-18)", () => {
    const ratio = feedbackCompletionRatio(
      metrics({ feedbackSubmitted: 2, attended: 4 }),
    );

    assert.equal(ratio.submitted, 2);
    assert.equal(ratio.denominator, 4);
    assert.equal(ratio.percent, 50);
  });
});
