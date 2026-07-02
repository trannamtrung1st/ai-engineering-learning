import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SessionsListToolbar } from "@/components/instructor/sessions-list-toolbar";

describe("SessionsListToolbar (AC-06 / TC-AC-06-021)", () => {
  it("renders search placeholder, status chips, and sort control", () => {
    render(
      <SessionsListToolbar
        searchInput=""
        onSearchInputChange={vi.fn()}
        onClearSearch={vi.fn()}
        statusFilter="all"
        onStatusFilterChange={vi.fn()}
        sortKey="date"
        onSortKeyChange={vi.fn()}
      />,
    );

    expect(screen.getByTestId("sessions-list-toolbar")).toBeInTheDocument();
    expect(screen.getByTestId("sessions-list-search")).toHaveAttribute(
      "placeholder",
      "Tìm theo lớp, môn…",
    );
    expect(screen.getByTestId("sessions-status-chip-all")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("sessions-status-chip-active")).toBeInTheDocument();
    expect(screen.getByTestId("sessions-list-sort")).toBeInTheDocument();
  });

  it("fires status chip and clear search handlers", () => {
    const onStatusFilterChange = vi.fn();
    const onClearSearch = vi.fn();

    render(
      <SessionsListToolbar
        searchInput="HESD"
        onSearchInputChange={vi.fn()}
        onClearSearch={onClearSearch}
        statusFilter="all"
        onStatusFilterChange={onStatusFilterChange}
        sortKey="date"
        onSortKeyChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId("sessions-status-chip-active"));
    expect(onStatusFilterChange).toHaveBeenCalledWith("active");

    fireEvent.click(screen.getByTestId("sessions-search-clear"));
    expect(onClearSearch).toHaveBeenCalled();
  });
});
