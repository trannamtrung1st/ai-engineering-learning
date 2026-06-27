import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../../..");

const PARTICIPANT_LISTING_PAGES = [
  "apps/web/src/app/(participant)/events/page.tsx",
  "apps/web/src/app/(participant)/registrations/page.tsx",
] as const;

const ORGANIZER_LISTING_PAGES = [
  "apps/web/src/app/(organizer)/organizer/events/page.tsx",
  "apps/web/src/app/(organizer)/organizer/check-in/page.tsx",
  "apps/web/src/app/(organizer)/organizer/events/[eventId]/registrations/page.tsx",
  "apps/web/src/app/(organizer)/organizer/events/[eventId]/eligibility/page.tsx",
] as const;

function readRepoFile(relativePath: string): string {
  return readFileSync(join(REPO_ROOT, relativePath), "utf8");
}

/**
 * AC-14 / FR-28 / FR-29 / FR-31 / NFR-05 / NFR-16: listing pages expose prev/next controls
 * and use server-driven pagination instead of rendering unbounded client-side datasets.
 */
describe("AC-14 — listing page pagination contract (FR-31, NFR-05, NFR-16)", () => {
  it("participant listing pages render Pagination with server page params", () => {
    for (const pagePath of PARTICIPANT_LISTING_PAGES) {
      const source = readRepoFile(pagePath);
      assert.match(
        source,
        /Pagination/,
        `${pagePath} must render Pagination controls`,
      );
      assert.match(
        source,
        /pageSize/,
        `${pagePath} must pass pageSize to the API`,
      );
      assert.match(
        source,
        /setPage|onPageChange/,
        `${pagePath} must wire page navigation`,
      );
      assert.match(
        source,
        /eventsQuery\.data\?\.items|pageSize:\s*EVENT_PAGE_SIZE|REGISTRATION_PAGE_SIZE/,
        `${pagePath} must use server-paginated list data`,
      );
    }
  });

  it("my registrations uses GET /me/registrations (no N+1 event fan-out)", () => {
    const registrationsPage = readRepoFile(PARTICIPANT_LISTING_PAGES[1]);
    assert.match(
      registrationsPage,
      /fetchMyRegistrations/,
      "registrations page must call fetchMyRegistrations",
    );
    assert.doesNotMatch(
      registrationsPage,
      /fetchEvents[\s\S]*fetchEvents/,
      "registrations page must not fan out per-event registration calls",
    );

    const participantApi = readRepoFile("apps/web/src/lib/participant-api.ts");
    assert.match(
      participantApi,
      /\/me\/registrations/,
      "participant API must use paginated /me/registrations endpoint",
    );
  });

  it("organizer operational tables use shared server pagination", () => {
    const tableSource = readRepoFile(
      "apps/web/src/components/organizer/server-paginated-table.tsx",
    );
    assert.match(tableSource, /Pagination/);
    assert.match(tableSource, /pageSize/);
    assert.match(tableSource, /onPageChange/);

    for (const pagePath of ORGANIZER_LISTING_PAGES) {
      const source = readRepoFile(pagePath);
      const usesServerTable =
        source.includes("ServerPaginatedTable") || source.includes("Pagination");
      assert.ok(
        usesServerTable,
        `${pagePath} must use Pagination or ServerPaginatedTable`,
      );
      assert.match(
        source,
        /pageSize|PAGE_SIZE|EVENT_PAGE_SIZE/,
        `${pagePath} must bound list page size`,
      );
    }
  });

  it("Pagination component exposes Previous and Next controls", () => {
    const pagination = readRepoFile("apps/web/src/components/ui/pagination.tsx");
    assert.match(pagination, /aria-label="Previous page"/);
    assert.match(pagination, /aria-label="Next page"/);
    assert.match(pagination, /disabled=\{!canPrev\}/);
    assert.match(pagination, /disabled=\{!canNext\}/);
  });
});
