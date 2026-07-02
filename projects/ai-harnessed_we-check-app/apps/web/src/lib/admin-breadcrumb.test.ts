import { describe, expect, it } from "vitest";
import { getAdminBreadcrumbItems } from "@/lib/admin-breadcrumb";
import { appCopy } from "@/lib/copy/status-labels";
import { userCopy } from "@/lib/copy/user-labels";

/** NFR-11 — admin breadcrumb reflects current page context */
describe("getAdminBreadcrumbItems (NFR-11)", () => {
  it("TC-NFR-11-017: /admin/users shows Người dùng not hub label", () => {
    const items = getAdminBreadcrumbItems("/admin/users");
    expect(items).toHaveLength(2);
    expect(items[0]?.label).toBe(appCopy.adminSection);
    expect(items[1]?.label).toBe(userCopy.pageTitle);
  });

  it("shows hub label on /admin", () => {
    const items = getAdminBreadcrumbItems("/admin");
    expect(items.at(-1)?.label).toBe("Bảng điều khiển");
  });

  it("shows create title on /admin/users/new", () => {
    const items = getAdminBreadcrumbItems("/admin/users/new");
    expect(items.map((item) => item.label)).toEqual([
      appCopy.adminSection,
      userCopy.pageTitle,
      userCopy.createTitle,
    ]);
  });
});
