import { SessionStatus } from "@wecheck/domain";
import { createBrowserRouter, RouterProvider, useRouteError } from "react-router-dom";
import { RootLayout } from "@/app/layout";
import { CreateClassSubjectPage } from "@/app/admin/classes/new/page";
import { AdminExportPage } from "@/app/admin/export/page";
import { AdminPolicyPage } from "@/app/admin/policy/page";
import { AdminReportsPage } from "@/app/admin/reports/page";
import { AdminUsersPage } from "@/app/admin/users/page";
import { CreateUserPage } from "@/app/admin/users/new/page";
import { EditUserPage } from "@/app/admin/users/[userId]/page";
import { AdminClassRosterPage } from "@/app/admin/rosters/[classCode]/page";
import { AdminRostersPage } from "@/app/admin/rosters/page";
import { RosterImportPage } from "@/app/admin/rosters/import/page";
import { CheckInPage } from "@/app/check-in/page";
import { ForbiddenRoutePage } from "@/app/forbidden/page";
import { HistoryPage } from "@/app/history/page";
import { LoginPage } from "@/app/login/page";
import { NotFoundRoutePage } from "@/app/not-found/page";
import { ReportsPage } from "@/app/reports/page";
import { SessionReportPage } from "@/app/reports/session-report-page";
import { CreateSessionPage } from "@/app/sessions/create-session-page";
import { QrPresentPage } from "@/app/sessions/[sessionId]/qr-present/page";
import { SessionDetailPage } from "@/app/sessions/session-detail-page";
import { SessionMonitorPage } from "@/app/sessions/[sessionId]/monitor/page";
import { SessionRosterPage } from "@/app/sessions/[sessionId]/roster/page";
import { SessionsListPage } from "@/app/sessions/page";
import { RequireAuth } from "@/components/auth/require-auth";
import { SetupGuard } from "@/components/auth/setup-guard";
import { AdminHomePage } from "@/app/admin/page";
import { SetupPage } from "@/app/setup/page";
import { AdminLayout } from "@/components/layout/admin-layout";
import { AuthLayout } from "@/components/layout/auth-layout";
import { InstructorLayout } from "@/components/layout/instructor-layout";
import { NotFoundPage } from "@/components/layout/not-found-page";
import { PageHeader } from "@/components/layout/page-header";
import { StudentLayout } from "@/components/layout/student-layout";
import { Badge, QrCountdown, StatusBadge } from "@/components/ui";
import { CheckInOutcomeShowcase } from "@/components/domain/check-in/check-in-outcome-panel";
import { useLiveCountdown } from "@/hooks/use-live-countdown";
import { appCopy } from "@/lib/copy/status-labels";

function ShellOverviewPage() {
  const { secondsRemaining } = useLiveCountdown();

  return (
    <main id="main-content" className="mx-auto max-w-[720px] px-4 py-8">
      <PageHeader
        title={appCopy.shellOverviewTitle}
        description={appCopy.shellOverviewDescription}
      />
      <div className="flex flex-wrap gap-3">
        <StatusBadge status={SessionStatus.Active} />
        <StatusBadge status={SessionStatus.Draft} />
        <Badge variant="outline">Thành phần dùng chung</Badge>
      </div>
      <div className="mt-8 rounded-md border border-border bg-surface-inverse p-6">
        <QrCountdown secondsRemaining={secondsRemaining} presentation />
      </div>
      <div className="mt-8">
        <h2 className="mb-4 text-h2 font-semibold">Các trạng thái điểm danh</h2>
        <CheckInOutcomeShowcase />
      </div>
    </main>
  );
}

function RouteErrorPage() {
  useRouteError();
  return (
    <main id="main-content" className="mx-auto max-w-[720px] px-4 py-8">
      <NotFoundPage />
    </main>
  );
}

const router = createBrowserRouter([
  {
    element: <RootLayout />,
    errorElement: (
      <RootLayout>
        <RouteErrorPage />
      </RootLayout>
    ),
    children: [
      {
        element: <SetupGuard />,
        children: [
          {
            index: true,
            element: <ShellOverviewPage />,
          },
          {
            path: "setup",
            element: <AuthLayout />,
            children: [{ index: true, element: <SetupPage /> }],
          },
          {
            path: "login",
            element: <AuthLayout />,
            children: [{ index: true, element: <LoginPage /> }],
          },
          {
            path: "forbidden",
            element: <ForbiddenRoutePage />,
          },
          {
            element: <RequireAuth />,
            children: [
              {
                element: <StudentLayout />,
                children: [
                  { path: "check-in", element: <CheckInPage /> },
                  { path: "history", element: <HistoryPage /> },
                ],
              },
              {
                element: <InstructorLayout />,
                children: [
                  { path: "sessions", element: <SessionsListPage /> },
                  { path: "sessions/new", element: <CreateSessionPage /> },
                  { path: "sessions/:sessionId/monitor", element: <SessionMonitorPage /> },
                  { path: "sessions/:sessionId/roster", element: <SessionRosterPage /> },
                  { path: "sessions/:id", element: <SessionDetailPage /> },
                  { path: "reports", element: <ReportsPage /> },
                  { path: "reports/sessions/:sessionId", element: <SessionReportPage /> },
                ],
              },
              {
                path: "sessions/:sessionId/qr-present",
                element: <QrPresentPage />,
              },
              {
                path: "admin",
                element: <AdminLayout />,
                children: [
                  { index: true, element: <AdminHomePage /> },
                  { path: "users", element: <AdminUsersPage /> },
                  { path: "users/new", element: <CreateUserPage /> },
                  { path: "users/:userId", element: <EditUserPage /> },
                  { path: "rosters", element: <AdminRostersPage /> },
                  { path: "rosters/import", element: <RosterImportPage /> },
                  { path: "rosters/:classCode", element: <AdminClassRosterPage /> },
                  { path: "classes/new", element: <CreateClassSubjectPage /> },
                  { path: "reports", element: <AdminReportsPage /> },
                  { path: "export", element: <AdminExportPage /> },
                  { path: "policy", element: <AdminPolicyPage /> },
                ],
              },
            ],
          },
          {
            path: "*",
            element: <NotFoundRoutePage />,
          },
        ],
      },
    ],
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
