import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import { KpiSummaryStrip } from "./kpi-summary-strip.js";

describe("KpiSummaryStrip", () => {
  const items = [
    { label: "Registrations", value: 3, hint: "All registration records" },
    { label: "Waitlist", value: 0 },
  ];

  it("preserves KPI layout without refresh affordance by default (NFR-06)", () => {
    const html = renderToStaticMarkup(<KpiSummaryStrip items={items} />);

    assert.match(html, /Registrations/);
    assert.match(html, /Waitlist/);
    assert.doesNotMatch(html, /Refreshing/);
    assert.doesNotMatch(html, /aria-busy="true"/);
  });

  it("shows subtle refreshing indicator while background poll is in flight (TC-NFR-06-006)", () => {
    const html = renderToStaticMarkup(
      <KpiSummaryStrip items={items} isRefreshing />,
    );

    assert.match(html, /Refreshing…/);
    assert.match(html, /aria-live="polite"/);
    assert.match(html, /aria-busy="true"/);
    assert.match(html, /Registrations/);
  });

  it("shows inline error with retry while preserving stale KPI layout (TC-NFR-06-012)", () => {
    const html = renderToStaticMarkup(
      <KpiSummaryStrip
        items={items}
        refreshError="Service unavailable"
        onRetryRefresh={() => undefined}
      />,
    );

    assert.match(html, /Could not refresh metrics/);
    assert.match(html, /Service unavailable/);
    assert.match(html, /Retry/);
    assert.match(html, /Registrations/);
    assert.match(html, /Waitlist/);
  });
});
