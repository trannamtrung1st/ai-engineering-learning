import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { AttendancePolicyForm } from "@/components/admin/attendance-policy-form";
import { policyCopy } from "@/lib/copy/policy-labels";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/policy-api", () => ({
  getAbsencePolicy: vi.fn(),
  updateAbsencePolicy: vi.fn(),
  mapPolicyDetailsToFieldErrors: vi.fn((details?: { field: string; message: string }[]) => {
    if (!details?.length) return {};
    return Object.fromEntries(details.map((d) => [d.field, d.message]));
  }),
}));

import { getAbsencePolicy, updateAbsencePolicy } from "@/lib/policy-api";

/** FR-16 / AC-16 / BR-05 — admin attendance policy form */
describe("AttendancePolicyForm (FR-16, AC-16, BR-05)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getAbsencePolicy).mockResolvedValue({
      ok: true,
      data: { thresholdPercent: 20, autoWarningEnabled: true },
    });
  });

  it("TC-FR-16-014 / TC-BR-05-014: loads default threshold 20% and auto-warning toggle", async () => {
    render(<AttendancePolicyForm />);

    await waitFor(() => {
      expect(screen.getByTestId("attendance-policy-form")).toBeInTheDocument();
    });

    expect(screen.getByTestId("absence-threshold-input")).toHaveValue(20);
    expect(screen.getByTestId("auto-warning-toggle")).toBeChecked();
    expect(screen.getByText(policyCopy.fieldThresholdHint)).toBeInTheDocument();
  });

  it("TC-FR-16-014: saves updated threshold with success toast", async () => {
    vi.mocked(updateAbsencePolicy).mockResolvedValue({
      ok: true,
      data: { thresholdPercent: 25, autoWarningEnabled: true },
    });

    render(<AttendancePolicyForm />);

    await waitFor(() => {
      expect(screen.getByTestId("absence-threshold-input")).toHaveValue(20);
    });

    fireEvent.change(screen.getByTestId("absence-threshold-input"), {
      target: { value: "25" },
    });
    fireEvent.click(screen.getByTestId("attendance-policy-submit"));

    await waitFor(() => {
      expect(updateAbsencePolicy).toHaveBeenCalledWith({
        thresholdPercent: 25,
        autoWarningEnabled: true,
      });
    });

    expect(toast.success).toHaveBeenCalledWith(policyCopy.saveSuccess);
    expect(screen.getByTestId("absence-threshold-input")).toHaveValue(25);
  });

  it("TC-AC-16-012 / TC-FR-16-010: shows inline validation for threshold out of range", async () => {
    render(<AttendancePolicyForm />);

    await waitFor(() => {
      expect(screen.getByTestId("absence-threshold-input")).toHaveValue(20);
    });

    fireEvent.change(screen.getByTestId("absence-threshold-input"), {
      target: { value: "0" },
    });
    fireEvent.click(screen.getByTestId("attendance-policy-submit"));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(policyCopy.thresholdRange);
    });
    expect(updateAbsencePolicy).not.toHaveBeenCalled();
  });

  it("TC-FR-16-014: persists auto-warning toggle when saving", async () => {
    vi.mocked(updateAbsencePolicy).mockResolvedValue({
      ok: true,
      data: { thresholdPercent: 20, autoWarningEnabled: false },
    });

    render(<AttendancePolicyForm />);

    await waitFor(() => {
      expect(screen.getByTestId("auto-warning-toggle")).toBeChecked();
    });

    fireEvent.click(screen.getByTestId("auto-warning-toggle"));
    fireEvent.click(screen.getByTestId("attendance-policy-submit"));

    await waitFor(() => {
      expect(updateAbsencePolicy).toHaveBeenCalledWith({
        thresholdPercent: 20,
        autoWarningEnabled: false,
      });
    });

    expect(screen.getByTestId("auto-warning-toggle")).not.toBeChecked();
  });

  it("maps API validation errors to threshold field", async () => {
    vi.mocked(updateAbsencePolicy).mockResolvedValue({
      ok: false,
      status: 422,
      error: {
        errorCode: "ValidationFailed",
        details: [
          {
            field: "thresholdPercent",
            code: "ValidationFailed",
            message: "Giá trị phải là số nguyên từ 1 đến 100",
          },
        ],
      },
    });

    vi.mocked(getAbsencePolicy).mockResolvedValue({
      ok: true,
      data: { thresholdPercent: 50, autoWarningEnabled: true },
    });

    render(<AttendancePolicyForm />);

    await waitFor(() => {
      expect(screen.getByTestId("attendance-policy-form")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("absence-threshold-input"), {
      target: { value: "50" },
    });
    fireEvent.click(screen.getByTestId("attendance-policy-submit"));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Giá trị phải là số nguyên từ 1 đến 100",
      );
    });
  });
});
