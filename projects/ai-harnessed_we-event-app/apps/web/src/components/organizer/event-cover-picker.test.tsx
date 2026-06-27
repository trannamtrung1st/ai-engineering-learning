import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import { EventCoverPicker } from "./event-cover-picker.js";

describe("EventCoverPicker", () => {
  it("FR-35 / AC-17: exposes file picker, preview slot, and remove when cover exists", () => {
    const html = renderToStaticMarkup(
      <EventCoverPicker
        token="test-token"
        eventId="evt-1"
        initialCoverImageUrl="/api/v1/media/events/cover.png"
      />,
    );
    assert.match(html, /event-cover-picker/);
    assert.match(html, /event-cover-file-input/);
    assert.match(html, /Replace cover/);
    assert.match(html, /Remove/);
    assert.match(html, /event-cover-image/);
    assert.match(html, /image\/jpeg,image\/png,image\/webp/);
  });

  it("FR-35: create mode shows choose cover and placeholder without eventId", () => {
    const html = renderToStaticMarkup(
      <EventCoverPicker token="test-token" />,
    );
    assert.match(html, /Choose cover/);
    assert.match(html, /event-cover-placeholder/);
    assert.doesNotMatch(html, /Remove/);
  });

  it("FR-35: documents 5 MB limit in helper copy", () => {
    const html = renderToStaticMarkup(
      <EventCoverPicker token="test-token" eventId="evt-1" />,
    );
    assert.match(html, /5 MB/);
    assert.match(html, /JPEG, PNG, or WebP/);
  });
});
