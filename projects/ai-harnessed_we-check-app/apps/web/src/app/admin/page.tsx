import { Link } from "react-router-dom";
import {
  BarChart3,
  Download,
  Settings,
  Upload,
  UserPlus,
  Users,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { adminHubCopy } from "@/lib/copy/setup-labels";

const hubCards = [
  {
    to: "/admin/users",
    title: adminHubCopy.usersCard,
    description: adminHubCopy.usersDescription,
    icon: Users,
    testId: "admin-hub-users",
  },
  {
    to: "/admin/rosters",
    title: adminHubCopy.rostersCard,
    description: adminHubCopy.rostersDescription,
    icon: Upload,
    testId: "admin-hub-rosters",
  },
  {
    to: "/admin/classes/new",
    title: adminHubCopy.classesCard,
    description: adminHubCopy.classesDescription,
    icon: UserPlus,
    testId: "admin-hub-classes",
  },
  {
    to: "/admin/rosters/import",
    title: adminHubCopy.importCard,
    description: adminHubCopy.importDescription,
    icon: Upload,
    testId: "admin-hub-import",
  },
  {
    to: "/admin/reports",
    title: adminHubCopy.reportsCard,
    description: adminHubCopy.reportsDescription,
    icon: BarChart3,
    testId: "admin-hub-reports",
  },
  {
    to: "/admin/export",
    title: adminHubCopy.exportCard,
    description: adminHubCopy.exportDescription,
    icon: Download,
    testId: "admin-hub-export",
  },
  {
    to: "/admin/policy",
    title: adminHubCopy.policyCard,
    description: adminHubCopy.policyDescription,
    icon: Settings,
    testId: "admin-hub-policy",
  },
] as const;

/** FR-17 / AC-17 — post-bootstrap admin landing hub */
export function AdminHomePage() {
  return (
    <div data-testid="admin-home-page">
      <PageHeader
        title={adminHubCopy.pageTitle}
        description={adminHubCopy.pageDescription}
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {hubCards.map((card) => {
          const Icon = card.icon;
          return (
            <Link
              key={card.to}
              to={card.to}
              className="group block rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
              data-testid={card.testId}
            >
              <Card className="h-full transition-shadow group-hover:shadow-md">
                <CardContent className="flex flex-col gap-3 p-5">
                  <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary-50 text-primary-700">
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </div>
                  <div>
                    <h2 className="text-h3 font-semibold text-text-primary">{card.title}</h2>
                    <p className="mt-1 text-body text-text-secondary">{card.description}</p>
                  </div>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
