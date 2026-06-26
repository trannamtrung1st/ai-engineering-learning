import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import { AppShell } from "./app-shell.js";
import { PageHeader } from "./page-header.js";

describe("AppShell layout", () => {
  it("renders participant chrome without side navigation", () => {
    const html = renderToStaticMarkup(
      <AppShell role="participant" userDisplayName="Alex Rivera">
        <PageHeader title="Browse events" subtitle="Discover upcoming sessions." />
      </AppShell>,
    );

    assert.match(html, /We Event/);
    assert.match(html, /Alex Rivera/);
    assert.match(html, /Browse events/);
    assert.doesNotMatch(html, /Section navigation/);
  });

  it("renders organizer context in the top bar", () => {
    const html = renderToStaticMarkup(
      <AppShell role="organizer-admin" organizationName="Campus Programs">
        <p>Operations workspace</p>
      </AppShell>,
    );

    assert.match(html, /Organizer Admin/);
    assert.match(html, /Campus Programs/);
    assert.match(html, /Operations workspace/);
  });
});
