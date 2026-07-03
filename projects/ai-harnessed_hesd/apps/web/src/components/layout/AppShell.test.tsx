import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AppShell } from "./AppShell";
import { SidebarNav } from "./SidebarNav";

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

  it("FR-14: staff shell composes persistent sidebar with logout footer", () => {
    render(
      <MemoryRouter>
        <AppShell
          sidebar={
            <SidebarNav items={[{ to: "/lecturer/sessions", label: "Phiên học" }]} />
          }
          header={<div>Header</div>}
        >
          <p>Workspace content</p>
        </AppShell>
      </MemoryRouter>,
    );

    expect(screen.getByRole("complementary", { name: "Điều hướng chính" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Đăng xuất" })).toBeInTheDocument();
  });
});
