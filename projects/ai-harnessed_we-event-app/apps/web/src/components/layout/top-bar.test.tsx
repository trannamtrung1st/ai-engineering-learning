import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import { TopBar } from "./top-bar.js";

describe("TopBar sign-out (FR-34, AC-15)", () => {
  it("renders account display name from session profile", () => {
    const html = renderToStaticMarkup(
      <TopBar role="participant" userDisplayName="Alex Rivera" />,
    );
    assert.match(html, /Alex Rivera/);
    assert.doesNotMatch(html, /participant-1/);
  });

  it("accepts sign-out handler for account menu wiring", () => {
    const html = renderToStaticMarkup(
      <TopBar
        role="participant"
        userDisplayName="Alex Rivera"
        onSignOut={() => undefined}
      />,
    );
    assert.match(html, /Account menu/);
    assert.match(html, /Alex Rivera/);
  });
});
