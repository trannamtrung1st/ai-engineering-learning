import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import { EVENT_STATES } from "@we-event/domain";

import { eventStateLabel } from "@/lib/domain-labels";

import { EventStateBadge } from "./event-state-badge.js";

describe("EventStateBadge (NFR-06)", () => {
  for (const state of EVENT_STATES) {
    it(`renders ${state} with semantic badgeStatus token`, () => {
      const { label, badgeStatus } = eventStateLabel(state);
      const html = renderToStaticMarkup(<EventStateBadge state={state} />);

      assert.match(html, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"));
      assert.match(html, new RegExp(`data-domain-status="${badgeStatus}"`));
      assert.match(html, new RegExp(`aria-label="Event status: ${label}"`));
    });
  }

  it("TC-NFR-06-017: uses CSS variable semantic variant, not outline/default utilities", () => {
    const html = renderToStaticMarkup(<EventStateBadge state="RegistrationOpen" />);

    assert.match(html, /data-domain-status="registrationOpen"/);
    assert.match(html, /bg-\[var\(--status-bg\)\]/);
    assert.doesNotMatch(html, /variant="outline"/);
  });
});
