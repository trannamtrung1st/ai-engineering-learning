import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { QrCountdownRing } from "./QrCountdownRing";

describe("QrCountdownRing (NFR-15)", () => {
  it("shows seconds remaining with accessible label", () => {
    const expiresAt = new Date(Date.now() + 12_000).toISOString();
    render(<QrCountdownRing expiresAt={expiresAt} />);
    expect(screen.getByLabelText(/Còn \d+ giây/)).toBeInTheDocument();
  });
});
