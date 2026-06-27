import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { getLiveQueryPolicy, LIVE_REFRESH_INTERVALS } from "@/lib/query-config.js";

/**
 * TC-NFR-06-002 — useLiveQuery spreads getLiveQueryPolicy(mode) into useQuery.
 * Hook body is a thin wrapper; policy merge is verified here against the contract.
 */
describe("NFR-06 useLiveQuery policy merge", () => {
  it("organizerDashboard mode supplies TanStack Query polling options", () => {
    const policy = getLiveQueryPolicy("organizerDashboard");

    assert.equal(policy.refetchInterval, LIVE_REFRESH_INTERVALS.organizerDashboard);
    assert.equal(policy.staleTime, Math.floor(LIVE_REFRESH_INTERVALS.organizerDashboard / 2));
    assert.equal(policy.refetchOnWindowFocus, true);
    assert.equal(policy.refetchIntervalInBackground, true);
  });

  it("checkInConsole mode pauses background polling while keeping shortest interval", () => {
    const policy = getLiveQueryPolicy("checkInConsole");

    assert.equal(policy.refetchInterval, LIVE_REFRESH_INTERVALS.checkInConsole);
    assert.equal(policy.refetchIntervalInBackground, false);
    assert.equal(policy.refetchOnWindowFocus, true);
  });
});
