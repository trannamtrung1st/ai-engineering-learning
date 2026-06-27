import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import { Pagination } from "./pagination.js";

describe("Pagination", () => {
  it("AC-14: shows page range, item range, and prev/next controls", () => {
    const html = renderToStaticMarkup(
      <Pagination
        page={2}
        pageCount={5}
        total={48}
        pageSize={12}
        onPageChange={() => {}}
      />,
    );
    assert.match(html, /Page 2 of 5/);
    assert.match(html, /Showing 13–24 of 48/);
    assert.match(html, /aria-label="Previous page"/);
    assert.match(html, /aria-label="Next page"/);
    assert.match(html, /aria-label="Pagination"/);
  });

  it("AC-14: disables previous on first page and next on last page", () => {
    const firstPage = renderToStaticMarkup(
      <Pagination page={1} pageCount={3} total={30} pageSize={10} onPageChange={() => {}} />,
    );
    assert.match(firstPage, /disabled/);

    const lastPage = renderToStaticMarkup(
      <Pagination page={3} pageCount={3} total={30} pageSize={10} onPageChange={() => {}} />,
    );
    const disabledCount = (lastPage.match(/disabled/g) ?? []).length;
    assert.ok(disabledCount >= 1);
  });
});
