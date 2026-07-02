import type { BreadcrumbItem } from "@/components/shared/navigation/breadcrumb";
import { adminNavItems, appCopy } from "@/lib/copy/status-labels";
import { userCopy } from "@/lib/copy/user-labels";
import { userImportCopy } from "@/lib/copy/user-import-labels";

const ADMIN_HUB_LABEL = "Bảng điều khiển";

/** NFR-11 — route-aware admin top bar breadcrumb */
export function getAdminBreadcrumbItems(pathname: string): BreadcrumbItem[] {
  const root: BreadcrumbItem = { label: appCopy.adminSection, to: "/admin" };

  if (pathname === "/admin" || pathname === "/admin/") {
    return [root, { label: ADMIN_HUB_LABEL }];
  }

  if (pathname.startsWith("/admin/users")) {
    const items: BreadcrumbItem[] = [
      root,
      { label: userCopy.pageTitle, to: "/admin/users" },
    ];
    if (pathname === "/admin/users/new") {
      items.push({ label: userCopy.createTitle });
    } else if (pathname === "/admin/users/import") {
      items.push({ label: userImportCopy.pageTitle });
    } else if (pathname !== "/admin/users" && /^\/admin\/users\/[^/]+$/.test(pathname)) {
      items.push({ label: userCopy.editTitle });
    }
    return items;
  }

  const matched = adminNavItems
    .filter((item) => item.to !== "/admin" && pathname.startsWith(item.to))
    .sort((a, b) => b.to.length - a.to.length)[0];

  if (matched) {
    return pathname === matched.to
      ? [root, { label: matched.label }]
      : [root, { label: matched.label, to: matched.to }];
  }

  return [root, { label: ADMIN_HUB_LABEL }];
}
