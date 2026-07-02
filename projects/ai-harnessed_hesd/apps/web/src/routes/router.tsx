import { Navigate, useRoutes } from "react-router-dom";
import { AdminLayout } from "./AdminLayout";
import { StaffLayout } from "./StaffLayout";
import { StudentLayout } from "./StudentLayout";
import { StudentAttendanceReportGuard } from "./pages/AttendanceReportPage";
import { AdminClassSectionsPage } from "./pages/AdminClassSectionsPage";
import { AdminEnrollmentsPage } from "./pages/AdminEnrollmentsPage";
import { AdminTermsPage } from "./pages/AdminTermsPage";
import { DesignSystemPage } from "./pages/DesignSystemPage";
import { LecturerRosterPage } from "./pages/LecturerRosterPage";
import { LecturerSessionPage } from "./pages/LecturerSessionPage";
import { LecturerSessionsListPage } from "./pages/LecturerSessionsListPage";
import { LoginPage } from "./pages/LoginPage";
import { StudentAttendanceHistoryPage } from "./pages/StudentAttendanceHistoryPage";
import { StudentCheckInPage } from "./pages/StudentCheckInPage";

export function AppRouter() {
  return useRoutes([
    { index: true, element: <Navigate to="/showcase" replace /> },
    { path: "showcase", element: <DesignSystemPage /> },
    {
      element: <StudentLayout />,
      children: [
        { path: "login", element: <LoginPage /> },
        { path: "check-in", element: <StudentCheckInPage /> },
        { path: "me/attendance", element: <StudentAttendanceHistoryPage /> },
      ],
    },
    {
      element: <AdminLayout />,
      children: [
        { path: "admin/terms", element: <AdminTermsPage /> },
        { path: "admin/class-sections", element: <AdminClassSectionsPage /> },
        { path: "admin/class-sections/:sectionId/enrollments", element: <AdminEnrollmentsPage /> },
      ],
    },
    {
      element: <StaffLayout />,
      children: [
        { path: "lecturer/sessions", element: <LecturerSessionsListPage /> },
        { path: "lecturer/sessions/:sessionId", element: <LecturerSessionPage /> },
        { path: "lecturer/sessions/:sessionId/roster", element: <LecturerRosterPage /> },
        { path: "reports/attendance", element: <StudentAttendanceReportGuard /> },
      ],
    },
  ]);
}
