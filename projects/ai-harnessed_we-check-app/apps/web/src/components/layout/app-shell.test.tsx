import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AdminLayout } from "@/components/layout/admin-layout";
import { FullscreenLayout } from "@/components/layout/fullscreen-layout";
import { InstructorLayout } from "@/components/layout/instructor-layout";
import { StudentLayout } from "@/components/layout/student-layout";
import { QrCountdown } from "@/components/ui/qr-countdown";
import {
  adminNavItems,
  appCopy,
  instructorNavItems,
  studentNavItems,
} from "@/lib/copy/status-labels";

function renderWithOutlet(ui: React.ReactElement, path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="*" element={ui}>
          <Route index element={<p>Nội dung trang</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

/** NFR-17 role shells use Vietnamese navigation copy; NFR-06 QR countdown tokens */
describe("App shell layouts (NFR-17, NFR-06)", () => {
  it("StudentLayout renders Vietnamese bottom navigation", () => {
    renderWithOutlet(<StudentLayout />, "/check-in");
    expect(screen.getByTestId("student-layout")).toBeInTheDocument();
    for (const item of studentNavItems) {
      expect(screen.getByRole("link", { name: item.label })).toBeInTheDocument();
    }
  });

  it("InstructorLayout renders Vietnamese sidebar navigation", () => {
    renderWithOutlet(<InstructorLayout />, "/sessions");
    expect(screen.getByTestId("instructor-layout")).toBeInTheDocument();
    for (const item of instructorNavItems) {
      expect(screen.getAllByRole("link", { name: item.label }).length).toBeGreaterThan(0);
    }
  });

  it("AdminLayout renders Quản trị header and Vietnamese admin nav", () => {
    renderWithOutlet(<AdminLayout />, "/admin/users");
    expect(screen.getByTestId("admin-layout")).toBeInTheDocument();
    expect(screen.getAllByText(appCopy.adminSection).length).toBeGreaterThan(0);
    for (const item of adminNavItems) {
      expect(screen.getAllByRole("link", { name: item.label }).length).toBeGreaterThan(0);
    }
  });

  it("FullscreenLayout shows Vietnamese exit control and QR countdown", () => {
    render(<FullscreenLayout secondsRemaining={8} />);
    expect(screen.getByText(appCopy.exitFullscreen)).toBeInTheDocument();
    expect(screen.getByTestId("qr-countdown")).toHaveTextContent("Mã mới sau 8 giây");
  });

  it("QrCountdown switches to warning state at 10 seconds or below (NFR-06)", () => {
    const { rerender } = render(<QrCountdown secondsRemaining={15} />);
    expect(screen.getByTestId("qr-countdown")).toHaveClass("text-qr-accent");

    rerender(<QrCountdown secondsRemaining={10} />);
    expect(screen.getByTestId("qr-countdown")).toHaveClass("text-qr-warning");
  });

  it("QrCountdown presentation mode uses warning color at 10 seconds or below (NFR-06)", () => {
    const { rerender } = render(<QrCountdown secondsRemaining={15} presentation />);
    expect(screen.getByTestId("qr-countdown")).toHaveClass("text-qr-countdown");

    rerender(<QrCountdown secondsRemaining={10} presentation />);
    expect(screen.getByTestId("qr-countdown")).toHaveClass("text-qr-warning");
  });
});
