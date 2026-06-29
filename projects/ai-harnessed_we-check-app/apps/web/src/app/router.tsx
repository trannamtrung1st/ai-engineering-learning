import { SessionStatus } from "@wecheck/domain";
import { createBrowserRouter, RouterProvider, useRouteError } from "react-router-dom";
import { RootLayout } from "@/app/layout";
import { AdminExportPage } from "@/app/admin/export/page";
import { AdminReportsPage } from "@/app/admin/reports/page";
import { RosterImportPage } from "@/app/admin/rosters/import/page";
import { CheckInPage } from "@/app/check-in/page";
import { ForbiddenRoutePage } from "@/app/forbidden/page";
import { HistoryPage } from "@/app/history/page";
import { LoginPage } from "@/app/login/page";
import { NotFoundRoutePage } from "@/app/not-found/page";
import { ReportsPage } from "@/app/reports/page";
import { CreateSessionPage } from "@/app/sessions/create-session-page";
import { QrPresentPage } from "@/app/sessions/[sessionId]/qr-present/page";
import { SessionDetailPage } from "@/app/sessions/session-detail-page";
import { SessionMonitorPage } from "@/app/sessions/[sessionId]/monitor/page";
import { SessionsListPage } from "@/app/sessions/page";
import { RequireAuth } from "@/components/auth/require-auth";
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

function PlaceholderPage({ title }: { title: string }) {
  return <PageHeader title={title} description="Màn hình nghiệp vụ sẽ được bổ sung ở các slice tiếp theo." />;
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
        index: true,
        element: <ShellOverviewPage />,
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
              { path: "sessions/:id", element: <SessionDetailPage /> },
              { path: "reports", element: <ReportsPage /> },
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
              { path: "users", element: <PlaceholderPage title="Người dùng" /> },
              { path: "rosters", element: <PlaceholderPage title="Danh sách lớp" /> },
              { path: "rosters/import", element: <RosterImportPage /> },
              { path: "reports", element: <AdminReportsPage /> },
              { path: "export", element: <AdminExportPage /> },
              { path: "policy", element: <PlaceholderPage title="Chính sách" /> },
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
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
