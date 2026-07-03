/**
 * Traceability: FR-25 BR-20
 * TC-FR-25-015 TC-BR-20-015
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PolicyResolutionSummary } from "./PolicyResolutionSummary";
import { mergeDraftIntoEffectivePreview } from "../../lib/policy/resolve-preview";

describe("PolicyResolutionSummary (FR-25 BR-20)", () => {
  it("TC-FR-25-015: accordion shows precedence chain and per-field source badges", () => {
    const preview = mergeDraftIntoEffectivePreview(
      {
        values: {
          presentWindowMinutes: 10,
          lateWindowMinutes: 15,
          manualEditWindowHours: 24,
          gpsRequired: false,
          gpsRadiusMeters: 100,
        },
        sources: {
          presentWindowMinutes: "Institution",
          lateWindowMinutes: "Institution",
          manualEditWindowHours: "Institution",
          gpsRequired: "Institution",
          gpsRadiusMeters: "Institution",
        },
      },
      "ClassSection",
      { presentWindowMinutes: 20 },
    );

    render(<PolicyResolutionSummary preview={preview} />);

    expect(screen.getAllByText("Lớp học phần").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Toàn trường").length).toBeGreaterThan(0);
    expect(screen.getByText("20")).toBeInTheDocument();
  });
});
