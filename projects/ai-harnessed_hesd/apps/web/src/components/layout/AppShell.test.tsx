import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AppShell } from "./AppShell";

describe("AppShell (FR-14 staff layout)", () => {
  it("renders skip link and main landmark", () => {
    render(
      <MemoryRouter>
        <AppShell
          sidebar={<nav>Sidebar</nav>}
          header={<div>Header</div>}
        >
          <p>Workspace content</p>
        </AppShell>
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "Bỏ qua đến nội dung chính" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveTextContent("Workspace content");
  });
});
