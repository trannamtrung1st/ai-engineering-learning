import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import { Badge } from "./badge.js";

describe("Badge", () => {
  it("renders icon and label for domain status tokens", () => {
    const html = renderToStaticMarkup(<Badge status="registered" />);
    assert.match(html, /Registered/);
    assert.match(html, /data-domain-status="registered"/);
    assert.match(html, /--status-bg/);
    assert.match(html, /--status-fg/);
    assert.doesNotMatch(html, /--color-bg-subtle/);
    assert.match(html, /aria-hidden/);
  });

  it("supports custom children while keeping semantic status styling", () => {
    const html = renderToStaticMarkup(
      <Badge status="waitlisted">Queue position 3</Badge>,
    );
    assert.match(html, /Queue position 3/);
    assert.match(html, /data-domain-status="waitlisted"/);
  });
});
