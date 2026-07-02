import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FeedbackAlert } from "./FeedbackAlert";

describe("FeedbackAlert (NFR-14)", () => {
  it("renders danger variant with title and body", () => {
    render(
      <FeedbackAlert variant="danger" title="Mã QR đã hết hạn">
        Vui lòng quét mã mới.
      </FeedbackAlert>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Mã QR đã hết hạn");
    expect(screen.getByText("Vui lòng quét mã mới.")).toBeInTheDocument();
  });
});
