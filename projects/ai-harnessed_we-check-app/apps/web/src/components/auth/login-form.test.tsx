import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { UserRole } from "@wecheck/domain";
import { LoginForm } from "@/components/auth/login-form";
import { authMessages } from "@/lib/copy/checkin-messages";

/** AC-02 / FR-02 / BR-06 — LoginForm validation and redirect behavior */
describe("LoginForm (AC-02, FR-02, BR-06, NFR-16)", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        json: async () => ({ errorCode: "InvalidCredentials" }),
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

  function renderForm(initialPath = "/login") {
    return render(
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/login" element={<LoginForm />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  async function submitLogin(email: string, password: string) {
    fireEvent.change(screen.getByLabelText(authMessages.emailLabel), {
      target: { value: email },
    });
    fireEvent.change(screen.getByLabelText(authMessages.passwordLabel), {
      target: { value: password },
    });
    fireEvent.submit(screen.getByTestId("login-form"));
  }

  it("renders Vietnamese labels (FR-02, NFR-17)", () => {
    renderForm();
    expect(screen.getByLabelText(authMessages.emailLabel)).toBeInTheDocument();
    expect(screen.getByLabelText(authMessages.passwordLabel)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: authMessages.submitLabel })).toBeInTheDocument();
  });

  it("shows invalid credentials alert on 401 InvalidCredentials (TC-FR-02-020)", async () => {
    renderForm();
    await submitLogin("student@example.edu.vn", "wrong-pass");

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(authMessages.invalidCredentials);
    });
  });

  it("shows deactivated account alert on 403 AccountDeactivated", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({ errorCode: "AccountDeactivated" }),
    } as Response);

    renderForm();
    await submitLogin("deactivated@example.edu.vn", "StudentPass8");

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(authMessages.accountDeactivated);
    });
  });

  it("sends returnUrl in login body and navigates to redirectTo (TC-AC-02-002)", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        user: { id: "u1", role: UserRole.Student },
        redirectTo: "/check-in?token=test-token",
      }),
    } as Response);

    renderForm("/login?returnUrl=%2Fcheck-in%3Ftoken%3Dtest-token");
    await submitLogin("student@example.edu.vn", "StudentPass8");

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/auth/login"),
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            email: "student@example.edu.vn",
            password: "StudentPass8",
            returnUrl: "/check-in?token=test-token",
          }),
        }),
      );
    });

    await waitFor(() => {
      expect(window.location.href).toBe("/check-in?token=test-token");
    });
  });

  it("redirects instructor to /sessions when no returnUrl (TC-FR-02-021)", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        user: { id: "u2", role: UserRole.Instructor },
      }),
    } as Response);

    renderForm("/login");
    await submitLogin("instructor@example.edu.vn", "InstructorPass8");

    await waitFor(() => {
      expect(window.location.href).toBe("/sessions");
    });
  });

  it("shows session expired alert when sessionExpired=1 (AC-02c, NFR-16)", () => {
    renderForm("/login?sessionExpired=1&returnUrl=%2Fcheck-in");
    expect(screen.getByRole("alert")).toHaveTextContent(authMessages.sessionExpired);
  });
});
