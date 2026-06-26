import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import { CapacityMeter } from "./capacity-meter.js";

describe("CapacityMeter", () => {
  it("AC-11: shows registered/capacity ratio and waitlist count", () => {
    const html = renderToStaticMarkup(
      <CapacityMeter registered={42} capacity={50} waitlist={3} />,
    );
    assert.match(html, /42 \/ 50 registered/);
    assert.match(html, /Waitlist: 3/);
    assert.match(html, /role="progressbar"/);
  });

  it("warns when nearing or at capacity", () => {
    const nearing = renderToStaticMarkup(
      <CapacityMeter registered={46} capacity={50} waitlist={0} />,
    );
    assert.match(nearing, /Nearing capacity/);

    const full = renderToStaticMarkup(
      <CapacityMeter registered={50} capacity={50} waitlist={2} />,
    );
    assert.match(full, /At capacity/);
  });
});
