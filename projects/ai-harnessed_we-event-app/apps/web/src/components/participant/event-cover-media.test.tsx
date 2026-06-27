import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import { EventCoverMedia } from "./event-cover-media.js";

describe("EventCoverMedia", () => {
  it("FR-36 / AC-17: renders 16:9 placeholder when coverImageUrl is absent", () => {
    const html = renderToStaticMarkup(
      <EventCoverMedia
        coverImageUrl={null}
        alt="Event cover placeholder"
        variant="thumbnail"
      />,
    );
    assert.match(html, /event-cover-placeholder/);
    assert.match(html, /aspect-video/);
    assert.doesNotMatch(html, /event-cover-image/);
  });

  it("FR-36 / AC-17: renders next/image cover for thumbnail variant", () => {
    const html = renderToStaticMarkup(
      <EventCoverMedia
        coverImageUrl="/api/v1/media/events/cover.png"
        alt="Cover image for Summit"
        variant="thumbnail"
      />,
    );
    assert.match(html, /event-cover-image/);
    assert.match(html, /aspect-video/);
    assert.match(html, /Cover image for Summit/);
    assert.doesNotMatch(html, /event-cover-placeholder/);
  });

  it("FR-36: renders hero variant with wider aspect ratio", () => {
    const html = renderToStaticMarkup(
      <EventCoverMedia
        coverImageUrl="/api/v1/media/events/cover.png"
        alt="Cover image for Summit"
        variant="hero"
      />,
    );
    assert.match(html, /event-cover-image/);
    assert.match(html, /aspect-\[21\/9\]/);
  });

  it("TC-AC-17-013 / FR-36: detail hero placeholder when no cover", () => {
    const html = renderToStaticMarkup(
      <EventCoverMedia
        coverImageUrl={undefined}
        alt="Event cover placeholder"
        variant="hero"
      />,
    );
    assert.match(html, /event-cover-placeholder/);
    assert.match(html, /aspect-\[21\/9\]/);
  });
});
