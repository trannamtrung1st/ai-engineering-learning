/**
 * Traceability: FR-25 BR-20
 * TC-FR-25-015 TC-BR-20-015
 */
import { describe, expect, it } from "vitest";
import { mergeDraftIntoEffectivePreview } from "./resolve-preview";

describe("resolve-preview (FR-25 BR-20)", () => {
  it("TC-FR-25-015: draft section present window overrides effective preview source", () => {
    const base = {
      values: {
        presentWindowMinutes: 10,
        lateWindowMinutes: 15,
        manualEditWindowHours: 24,
        gpsRequired: false,
        gpsRadiusMeters: 100,
      },
      sources: {
        presentWindowMinutes: "Institution" as const,
        lateWindowMinutes: "Institution" as const,
        manualEditWindowHours: "Institution" as const,
        gpsRequired: "Institution" as const,
        gpsRadiusMeters: "Institution" as const,
      },
    };

    const preview = mergeDraftIntoEffectivePreview(base, "ClassSection", {
      presentWindowMinutes: 25,
    });

    const presentField = preview.fields.find((field) => field.key === "presentWindowMinutes");
    expect(presentField?.value).toBe(25);
    expect(presentField?.source).toBe("ClassSection");

    const lateField = preview.fields.find((field) => field.key === "lateWindowMinutes");
    expect(lateField?.source).toBe("Institution");
  });
});
