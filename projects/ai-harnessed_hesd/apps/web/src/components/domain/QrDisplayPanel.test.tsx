/**
 * Traceability: FR-14 NFR-15 AC-UI-06 AC-02 AC-05
 * TC-FR-14-011 TC-FR-14-013 TC-NFR-15-001 TC-NFR-15-006 TC-NFR-15-010 TC-NFR-15-012 TC-NFR-15-014
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PROJECTION_QR_SIZE, QrDisplayPanel } from "./QrDisplayPanel";

describe("QrDisplayPanel (FR-14 NFR-15 AC-UI-06)", () => {
  it("TC-NFR-15-001 AC-UI-06: renders projection-ready high-contrast QR with session identity when Open", () => {
    render(
      <QrDisplayPanel
        sectionCode="CSE101-A"
        sessionName="Lập trình Web"
        sessionState="Open"
        qrData={{
          qrPayload: "attendly://check-in/demo",
          expiresAt: new Date(Date.now() + 30_000).toISOString(),
          tokenState: "Valid",
        }}
        projectionMode
      />,
    );

    expect(screen.getByText("CSE101-A")).toBeInTheDocument();
    expect(screen.getByText("Lập trình Web")).toBeInTheDocument();
    expect(screen.getByText("Đang mở")).toBeInTheDocument();
    const qr = screen.getByTestId("qr-display-canvas");
    expect(qr).toBeInTheDocument();
    expect(qr.getAttribute("height")).toBe(String(PROJECTION_QR_SIZE));
    expect(PROJECTION_QR_SIZE).toBeGreaterThanOrEqual(432);
  });

  it("TC-NFR-15-006 AC-UI-06 AC-05: Closed state hides projection QR per session close feedback", () => {
    render(
      <QrDisplayPanel
        sectionCode="CSE101-A"
        sessionName="Lập trình Web"
        sessionState="Closed"
        qrData={null}
      />,
    );

    expect(screen.queryByTestId("qr-display-canvas")).not.toBeInTheDocument();
  });
});
