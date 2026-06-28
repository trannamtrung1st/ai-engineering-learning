import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  AttendanceStatus,
  SessionStatus,
} from "@wecheck/domain";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  attendanceStatusLabels,
  sessionStatusLabels,
} from "@/lib/copy/status-labels";

/** NFR-17 — Vietnamese status labels from shared copy module */
describe("Badge and StatusBadge (NFR-17)", () => {
  it("renders Badge with Vietnamese child content", () => {
    render(<Badge>Thành phần dùng chung</Badge>);
    expect(screen.getByText("Thành phần dùng chung")).toBeInTheDocument();
  });

  it("maps SessionStatus to Vietnamese labels", () => {
    for (const status of Object.values(SessionStatus)) {
      const { unmount } = render(<StatusBadge status={status} />);
      expect(screen.getByText(sessionStatusLabels[status])).toBeInTheDocument();
      unmount();
    }
  });

  it("maps AttendanceStatus to Vietnamese labels", () => {
    for (const status of Object.values(AttendanceStatus)) {
      const { unmount } = render(<StatusBadge status={status} />);
      expect(screen.getByText(attendanceStatusLabels[status])).toBeInTheDocument();
      unmount();
    }
  });
});
