import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import { EventForm } from "./event-form.js";

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
