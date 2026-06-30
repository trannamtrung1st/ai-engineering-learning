import {
  BarChart3,
  Download,
  Settings,
  Upload,
  UserPlus,
  Users,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { RoleHomeHub } from "@/components/layout/role-home-hub";
import { adminHubCopy } from "@/lib/copy/setup-labels";

const adminHubIcons = {
  "/admin/users": Users,
  "/admin/rosters": Upload,
  "/admin/classes/new": UserPlus,
  "/admin/rosters/import": Upload,
  "/admin/reports": BarChart3,
  "/admin/export": Download,
  "/admin/policy": Settings,
} as const;

/** FR-17 / FR-18 / AC-18 — post-bootstrap admin landing hub */
export function AdminHomePage() {
  return (
    <div data-testid="admin-home-page">
      <PageHeader
        title={adminHubCopy.pageTitle}
        description={adminHubCopy.pageDescription}
      />
      <RoleHomeHub variant="admin" icons={adminHubIcons} />
    </div>
  );
}
