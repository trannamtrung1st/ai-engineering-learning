import { Navigate, useRoutes } from "react-router-dom";
import { StaffLayout } from "./StaffLayout";
import { StudentLayout } from "./StudentLayout";
import { DesignSystemPage } from "./pages/DesignSystemPage";
import { LecturerSessionPage } from "./pages/LecturerSessionPage";
import { LoginPage } from "./pages/LoginPage";
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
      ],
    },
    {
      element: <StaffLayout />,
      children: [{ path: "lecturer/sessions/:sessionId", element: <LecturerSessionPage /> }],
    },
  ]);
}
