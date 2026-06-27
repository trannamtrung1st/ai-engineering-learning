import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import { EmptyFailureBlock } from "./empty-failure-block.js";

describe("EmptyFailureBlock", () => {
  it("renders retry action for failure variant when actionLabel and onAction are set (NFR-06)", () => {
    const html = renderToStaticMarkup(
      <EmptyFailureBlock
        variant="failure"
        title="Could not load dashboard"
        description="Service unavailable"
        actionLabel="Retry"
        onAction={() => undefined}
      />,
    );

    assert.match(html, /Could not load dashboard/);
    assert.match(html, /Service unavailable/);
    assert.match(html, /Retry/);
  });

  it("omits retry action for failure variant when actionLabel is absent", () => {
    const html = renderToStaticMarkup(
      <EmptyFailureBlock
        variant="failure"
        title="Access denied"
        description="You are not assigned to this event."
      />,
    );

    assert.match(html, /Access denied/);
    assert.doesNotMatch(html, /Retry/);
  });
});
