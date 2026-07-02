import { Navigate, useRoutes } from "react-router-dom";
import { StaffLayout } from "./StaffLayout";
import { StudentLayout } from "./StudentLayout";
import { StudentAttendanceReportGuard } from "./pages/AttendanceReportPage";
import { DesignSystemPage } from "./pages/DesignSystemPage";
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
      element: <StaffLayout />,
      children: [
        { path: "lecturer/sessions", element: <LecturerSessionsListPage /> },
        { path: "lecturer/sessions/:sessionId", element: <LecturerSessionPage /> },
        { path: "reports/attendance", element: <StudentAttendanceReportGuard /> },
      ],
    },
  ]);
}
