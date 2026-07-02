import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ErrorCode } from "@attendly/domain";
import { AttemptOutcomeCell } from "./AttemptOutcomeCell";

/** Traceability: FR-19 AC-18 */
describe("AttemptOutcomeCell — FR-19 AC-18", () => {
  it("renders rejection badge with tooltip title for OutOfRadius", () => {
    render(<AttemptOutcomeCell outcome={ErrorCode.OutOfRadius} />);
    expect(screen.getByText("Ngoài phạm vi")).toBeInTheDocument();
  });

  it("renders dash when outcome is Success", () => {
    render(<AttemptOutcomeCell outcome="Success" />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
