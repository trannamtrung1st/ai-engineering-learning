import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import { EventCard } from "./event-card.js";

describe("EventCard", () => {
  const event = {
    eventId: "evt-1",
    name: "We Event Summit",
    state: "RegistrationOpen" as const,
    startAt: "2026-06-15T10:00:00.000Z",
    location: "Main Hall",
  };

  it("FR-28: renders event discovery card with state badge and detail link", () => {
    const html = renderToStaticMarkup(<EventCard event={event} />);
    assert.match(html, /We Event Summit/);
    assert.match(html, /href="\/events\/evt-1"/);
    assert.match(html, /Registration open/i);
    assert.match(html, /data-domain-status="registrationOpen"/);
    assert.match(html, /Not registered/);
  });

  it("FR-10: surfaces participant registration status when provided", () => {
    const html = renderToStaticMarkup(
      <EventCard event={event} registrationState="Registered" />,
    );
    assert.match(html, /Registered/);
    assert.match(html, /data-domain-status="registered"/);
    assert.doesNotMatch(html, /Not registered/);
  });

  it("shows status unavailable when registration lookup fails", () => {
    const html = renderToStaticMarkup(
      <EventCard event={event} registrationError="Network error" />,
    );
    assert.match(html, /Status unavailable/);
  });
});
