import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import { FeedbackCompletionTracker } from "./feedback-completion-tracker.js";

describe("FeedbackCompletionTracker (FR-22)", () => {
  it("shows mandatory outstanding alert and pending link (TC-FR-22-009)", () => {
    const html = renderToStaticMarkup(
      <FeedbackCompletionTracker
        metrics={{
          registrations: 5,
          registeredSeats: 5,
          waitlist: 0,
          checkedIn: 0,
          attended: 4,
          eligible: 1,
          notEligible: 0,
          pendingEligibility: 0,
          feedbackSubmitted: 2,
          feedbackRequired: true,
          mandatoryFeedbackOutstanding: 2,
        }}
        links={{ registrations: "/organizer/events/e1/registrations" }}
      />,
    );

    assert.match(html, /Feedback completion/);
    assert.match(html, /Mandatory feedback outstanding/);
    assert.match(html, /2 attended participants still need/);
    assert.match(html, /Review pending feedback/);
    assert.match(html, /state=Attended/);
  });

  it("shows optional policy copy when feedback is not required (TC-FR-22-015)", () => {
    const html = renderToStaticMarkup(
      <FeedbackCompletionTracker
        metrics={{
          registrations: 0,
          registeredSeats: 0,
          waitlist: 0,
          checkedIn: 0,
          attended: 0,
          eligible: 0,
          notEligible: 0,
          pendingEligibility: 0,
          feedbackSubmitted: 0,
          feedbackRequired: false,
          mandatoryFeedbackOutstanding: 0,
        }}
        links={{ registrations: "/organizer/events/e1/registrations" }}
      />,
    );

    assert.match(html, /optional/);
    assert.doesNotMatch(html, /Mandatory feedback outstanding/);
  });
});
