/**
 * Traceability: FR-19 AC-18 AC-10
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ErrorCode } from "@attendly/domain";
import { AttemptOutcomeCell } from "./AttemptOutcomeCell";

describe("AttemptOutcomeCell — FR-19 AC-18 AC-10", () => {
  it("renders rejection badge with tooltip title for OutOfRadius", () => {
    render(<AttemptOutcomeCell outcome={ErrorCode.OutOfRadius} />);
    expect(screen.getByText("Ngoài phạm vi")).toBeInTheDocument();
  });

  it("TC-AC-10-010: renders visible distance review metadata for OutOfRadius", () => {
    render(
      <AttemptOutcomeCell
        outcome={ErrorCode.OutOfRadius}
        distanceMeters={162.8}
        allowedRadiusMeters={100}
      />,
    );
    expect(screen.getByTestId("attempt-outcome-distance")).toHaveTextContent("163m · giới hạn 100m");
  });

  it("renders dash when outcome is Success", () => {
    render(<AttemptOutcomeCell outcome="Success" />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
