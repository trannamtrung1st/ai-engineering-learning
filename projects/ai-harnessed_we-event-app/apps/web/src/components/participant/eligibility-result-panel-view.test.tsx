import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import type { EligibilityResult } from "@/lib/participant-api";

import { EligibilityResultPanelView } from "./eligibility-result-panel-view.js";

function buildEligibility(
  overrides: Partial<EligibilityResult> = {},
): EligibilityResult {
  return {
    eligibilityId: "elig-1",
    eventId: "evt-1",
    registrationId: "reg-1",
    participantId: "part-1",
    result: "Eligible",
    reasonCode: "ELIGIBLE",
    reasonText: "Attendance and mandatory feedback requirements met.",
    evaluatedAt: "2025-06-01T18:00:00.000Z",
    overriddenBy: null,
    updatedAt: "2025-06-01T18:00:00.000Z",
    ...overrides,
  };
}

describe("EligibilityResultPanelView", () => {
  it("AC-09 / FR-20 / AC-09a / AC-09e / BR-19: renders Eligible result with human-readable reason", () => {
    const html = renderToStaticMarkup(
      <EligibilityResultPanelView eligibility={buildEligibility()} />,
    );
    assert.match(html, /Eligible/);
    assert.match(html, /Attendance and mandatory feedback requirements met/);
    assert.match(html, /Evaluated at/);
  });

  it("AC-09 / FR-20 / AC-09c / BR-14 / BR-18: renders NotEligible when mandatory feedback is missing", () => {
    const html = renderToStaticMarkup(
      <EligibilityResultPanelView
        eligibility={buildEligibility({
          result: "NotEligible",
          reasonCode: "NOT_ELIGIBLE_FEEDBACK",
          reasonText: "Mandatory feedback was not submitted within the configured window.",
        })}
      />,
    );
    assert.match(html, /Not eligible/);
    assert.match(html, /NOT_ELIGIBLE_FEEDBACK/);
    assert.match(html, /Mandatory feedback was not submitted/);
  });

  it("AC-09 / FR-20 / AC-09b / BR-17: renders Eligible when optional feedback policy applies", () => {
    const html = renderToStaticMarkup(
      <EligibilityResultPanelView
        eligibility={buildEligibility({
          reasonCode: "ELIGIBLE",
          reasonText: "Attendance requirement met. Feedback was optional for this event.",
        })}
      />,
    );
    assert.match(html, /Eligible/);
    assert.match(html, /Feedback was optional/);
  });

  it("AC-09 / FR-20 / AC-09d / BR-17: renders NotEligible with attendance reason for absent registration", () => {
    const html = renderToStaticMarkup(
      <EligibilityResultPanelView
        eligibility={buildEligibility({
          result: "NotEligible",
          reasonCode: "NOT_ELIGIBLE_ATTENDANCE",
          reasonText: "Participant was marked absent after attendance finalization.",
        })}
      />,
    );
    assert.match(html, /NOT_ELIGIBLE_ATTENDANCE/);
    assert.match(html, /marked absent/);
  });

  it("AC-09 / FR-20 / AC-09g / BR-19: reflects updated evaluation after feedback submission", () => {
    const before = renderToStaticMarkup(
      <EligibilityResultPanelView
        eligibility={buildEligibility({
          result: "NotEligible",
          reasonCode: "NOT_ELIGIBLE_FEEDBACK",
          reasonText: "Submit feedback to become eligible.",
          evaluatedAt: "2025-06-01T17:00:00.000Z",
        })}
      />,
    );
    const after = renderToStaticMarkup(
      <EligibilityResultPanelView
        eligibility={buildEligibility({
          result: "Eligible",
          reasonCode: "ELIGIBLE",
          reasonText: "Attendance and mandatory feedback requirements met.",
          evaluatedAt: "2025-06-01T18:30:00.000Z",
        })}
      />,
    );
    assert.match(before, /Not eligible/);
    assert.match(after, /Eligible/);
    assert.match(after, /mandatory feedback requirements met/);
  });

  it("AC-09 / FR-20 / AC-09f / FR-20a: shows terminal outcome fields required for participant self-service view", () => {
    const html = renderToStaticMarkup(
      <EligibilityResultPanelView eligibility={buildEligibility()} />,
    );
    assert.match(html, /ELIGIBLE/);
    assert.match(html, /Eligible/);
    assert.doesNotMatch(html, /Pending evaluation/);
  });
});
