import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { UserRole } from "@wecheck/domain";
import { SetupAdminForm } from "@/components/auth/setup-admin-form";
import { setupCopy } from "@/lib/copy/setup-labels";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

/** AC-17 / FR-17 / NFR-16 — SetupAdminForm validation and bootstrap submit */
describe("SetupAdminForm (AC-17, FR-17, NFR-16)", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({
          errorCode: "ValidationFailed",
          details: [{ field: "email", code: "DuplicateEmail", message: "Email đã tồn tại" }],
        }),
      }),
    );

    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, href: "" },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  async function fillAndSubmit() {
    fireEvent.change(screen.getByLabelText(setupCopy.fieldInstitutionalId), {
      target: { value: "ADMIN001" },
    });
    fireEvent.change(screen.getByLabelText(setupCopy.fieldDisplayName), {
      target: { value: "Nguyễn Văn Admin" },
    });
    fireEvent.change(screen.getByLabelText(setupCopy.fieldEmail), {
      target: { value: "admin@example.edu.vn" },
    });
    fireEvent.change(screen.getByLabelText(setupCopy.fieldPassword), {
      target: { value: "AdminPass8" },
    });
    fireEvent.submit(screen.getByTestId("setup-admin-form"));
  }

  it("renders Vietnamese setup fields (TC-AC-17-013, TC-FR-17-011)", () => {
    render(<SetupAdminForm />);
    expect(screen.getByLabelText(setupCopy.fieldInstitutionalId)).toBeInTheDocument();
    expect(screen.getByLabelText(setupCopy.fieldDisplayName)).toBeInTheDocument();
    expect(screen.getByLabelText(setupCopy.fieldEmail)).toBeInTheDocument();
    expect(screen.getByLabelText(setupCopy.fieldPassword)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: setupCopy.submitLabel }),
    ).toBeInTheDocument();
  });

  it("shows client-side validation for weak password (TC-FR-17-009)", async () => {
    render(<SetupAdminForm />);
    fireEvent.change(screen.getByLabelText(setupCopy.fieldInstitutionalId), {
      target: { value: "ADMIN001" },
    });
    fireEvent.change(screen.getByLabelText(setupCopy.fieldDisplayName), {
      target: { value: "Nguyễn Văn Admin" },
    });
    fireEvent.change(screen.getByLabelText(setupCopy.fieldEmail), {
      target: { value: "admin@example.edu.vn" },
    });
    fireEvent.change(screen.getByLabelText(setupCopy.fieldPassword), {
      target: { value: "short" },
    });
    fireEvent.submit(screen.getByTestId("setup-admin-form"));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Mật khẩu phải có ít nhất 8 ký tự");
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("maps API validation errors to inline fields (TC-FR-17-008, AC-17d)", async () => {
    render(<SetupAdminForm />);
    await fillAndSubmit();

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Email đã tồn tại");
    });
  });

  it("redirects to /admin hub on successful bootstrap (TC-AC-17-013, TC-FR-17-012, NFR-16-018)", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      status: 201,
      json: async () => ({
        user: {
          id: "u1",
          institutionalId: "ADMIN001",
          displayName: "Nguyễn Văn Admin",
          email: "admin@example.edu.vn",
          role: UserRole.TrainingOfficeAdmin,
        },
        session: {
          id: "s1",
          expiresAt: new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString(),
        },
      }),
    } as Response);

    render(<SetupAdminForm />);
    await fillAndSubmit();

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/setup/first-admin"),
        expect.objectContaining({
          method: "POST",
          credentials: "include",
          body: JSON.stringify({
            institutionalId: "ADMIN001",
            displayName: "Nguyễn Văn Admin",
            email: "admin@example.edu.vn",
            password: "AdminPass8",
          }),
        }),
      );
    });

    await waitFor(() => {
      expect(window.location.href).toBe("/admin");
    });
  });

  it("shows setup closed message on SetupAlreadyComplete (TC-AC-17-011)", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({
        errorCode: "SetupAlreadyComplete",
        message: "Hệ thống đã được thiết lập",
      }),
    } as Response);

    render(<SetupAdminForm />);
    await fillAndSubmit();

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(setupCopy.setupClosed);
    });
  });
});
