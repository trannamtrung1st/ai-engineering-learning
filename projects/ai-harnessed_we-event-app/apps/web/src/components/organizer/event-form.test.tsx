import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import { EventForm } from "./event-form.js";

describe("EventForm", () => {
  it("FR-01: renders basic event detail fields for create flow", () => {
    const html = renderToStaticMarkup(
      <EventForm submitLabel="Create event" onSubmit={async () => {}} />,
    );
    assert.match(html, /Event name/);
    assert.match(html, /Description/);
    assert.match(html, /Location/);
    assert.match(html, /Start \(local time\)/);
    assert.match(html, /End \(local time\)/);
  });

  it("FR-02 / FR-03: renders capacity and registration window fields", () => {
    const html = renderToStaticMarkup(
      <EventForm submitLabel="Save" onSubmit={async () => {}} />,
    );
    assert.match(html, /Capacity/);
    assert.match(html, /Waitlist/);
    assert.match(html, /Registration window/);
    assert.match(html, /Check-in window/);
    assert.match(html, /Feedback and certificate rules/);
  });

  it("AC-11: surfaces audit reason fields when editing post-open event", () => {
    const html = renderToStaticMarkup(
      <EventForm
        submitLabel="Save changes"
        eventState="RegistrationOpen"
        onSubmit={async () => {}}
      />,
    );
    assert.match(html, /Audit reason/);
    assert.match(html, /Reason code/);
    assert.match(html, /audit log/);
  });

  it("AC-11: omits audit reason section for Draft events", () => {
    const html = renderToStaticMarkup(
      <EventForm
        submitLabel="Save changes"
        eventState="Draft"
        onSubmit={async () => {}}
      />,
    );
    assert.doesNotMatch(html, /Audit reason/);
  });
});

describe("EventForm cover integration", () => {
  it("FR-35 / AC-17: renders cover picker when token is provided", () => {
    const html = renderToStaticMarkup(
      <EventForm
        submitLabel="Save"
        token="test-token"
        eventId="evt-1"
        initialCoverImageUrl="/api/v1/media/events/cover.png"
        onSubmit={async () => {}}
      />,
    );
    assert.match(html, /event-cover-picker/);
    assert.match(html, /Cover image/);
  });

  it("FR-35: omits cover picker without organizer token", () => {
    const html = renderToStaticMarkup(
      <EventForm submitLabel="Save" onSubmit={async () => {}} />,
    );
    assert.doesNotMatch(html, /event-cover-picker/);
  });
});
