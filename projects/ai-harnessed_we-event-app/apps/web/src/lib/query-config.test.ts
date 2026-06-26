import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { getLiveQueryPolicy, LIVE_REFRESH_INTERVALS } from "./query-config.js";

describe("NFR-06 live query polling policy", () => {
  it("uses shorter intervals for organizer operations than event discovery", () => {
    assert.ok(
      LIVE_REFRESH_INTERVALS.organizerDashboard <
        LIVE_REFRESH_INTERVALS.eventList,
    );
    assert.ok(
      LIVE_REFRESH_INTERVALS.checkInConsole <
        LIVE_REFRESH_INTERVALS.organizerDashboard,
    );
  });

  it("derives staleTime as half the refetch interval", () => {
    for (const mode of Object.keys(LIVE_REFRESH_INTERVALS) as Array<
      keyof typeof LIVE_REFRESH_INTERVALS
    >) {
      const policy = getLiveQueryPolicy(mode);
      assert.equal(
        policy.staleTime,
        Math.floor(LIVE_REFRESH_INTERVALS[mode] / 2),
      );
      assert.equal(policy.refetchInterval, LIVE_REFRESH_INTERVALS[mode]);
    }
  });

  it("pauses background polling on the check-in console", () => {
    assert.equal(getLiveQueryPolicy("checkInConsole").refetchIntervalInBackground, false);
    assert.equal(getLiveQueryPolicy("organizerDashboard").refetchIntervalInBackground, true);
  });
});
