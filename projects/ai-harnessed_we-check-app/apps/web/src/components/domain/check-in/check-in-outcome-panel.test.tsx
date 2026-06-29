import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { CheckInOutcomePanel } from "@/components/domain/check-in/check-in-outcome-panel";
import { LoginForm } from "@/components/auth/login-form";
import { useLiveCountdown } from "@/hooks/use-live-countdown";
import { MemoryRouter } from "react-router-dom";

/** NFR-17 — check-in outcome panel Vietnamese copy */
describe("CheckInOutcomePanel (NFR-17)", () => {
  it("renders Present success message and Xong CTA", () => {
    render(<CheckInOutcomePanel outcome="Present" />);
    expect(screen.getByTestId("check-in-outcome-Present")).toBeInTheDocument();
    expect(screen.getAllByText("Điểm danh thành công").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Xong" })).toBeInTheDocument();
  });

  it("renders ExpiredQr warning with Quét lại CTA", () => {
    render(<CheckInOutcomePanel outcome="ExpiredQr" />);
    expect(screen.getByText("Mã QR đã hết hạn, vui lòng quét mã mới")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Quét lại" })).toBeInTheDocument();
  });
});

/** NFR-06 — live countdown hook */
describe("useLiveCountdown (NFR-06)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function CountdownDisplay() {
    const { secondsRemaining } = useLiveCountdown({ initialSeconds: 5 });
    return <span data-testid="seconds">{secondsRemaining}</span>;
  }

  it("decrements every second", () => {
    render(<CountdownDisplay />);
    expect(screen.getByTestId("seconds")).toHaveTextContent("5");

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByTestId("seconds")).toHaveTextContent("4");

    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByTestId("seconds")).toHaveTextContent("1");
  });

  it("calls onCycleComplete and resets to 30", () => {
    const onCycleComplete = vi.fn();

    function ShortCycle() {
      const { secondsRemaining } = useLiveCountdown({
        initialSeconds: 2,
        onCycleComplete,
      });
      return <span data-testid="seconds">{secondsRemaining}</span>;
    }

    render(<ShortCycle />);
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(onCycleComplete).toHaveBeenCalled();
    expect(screen.getByTestId("seconds")).toHaveTextContent("30");
  });
});

/** NFR-17 — login form Vietnamese labels */
describe("LoginForm (NFR-17)", () => {
  it("renders Vietnamese form labels and submit button", () => {
    render(
      <MemoryRouter>
        <LoginForm />
      </MemoryRouter>,
    );
    expect(screen.getByLabelText("Email hoặc tên đăng nhập")).toBeInTheDocument();
    expect(screen.getByLabelText("Mật khẩu")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Đăng nhập" })).toBeInTheDocument();
  });
});
