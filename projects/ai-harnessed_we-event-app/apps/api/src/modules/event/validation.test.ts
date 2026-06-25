import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { VALIDATION_ERROR_CODES } from "@we-event/domain";
import { ApiError } from "../../errors/api-error.js";
import type { EventWithConfig, RuleConfigInput } from "./types.js";
import {
  assertPublishReady,
  resolveTransition,
  validateCreateInput,
  validateRuleConfig,
  validateUpdateInput,
} from "./validation.js";

function defaultWindows() {
  const now = Date.now();
  return {
    open: new Date(now + 86_400_000).toISOString(),
    close: new Date(now + 172_800_000).toISOString(),
    regOpen: new Date(now).toISOString(),
    regClose: new Date(now + 86_400_000).toISOString(),
  };
}

function buildRuleConfig(overrides: Partial<RuleConfigInput> = {}): RuleConfigInput {
  const windows = defaultWindows();
  return {
    capacity: 10,
    waitlistEnabled: false,
    registrationOpenAt: windows.regOpen,
    registrationCloseAt: windows.regClose,
    checkinOpenAt: windows.regOpen,
    checkinCloseAt: windows.regClose,
    feedbackOpenAt: windows.regOpen,
    feedbackCloseAt: windows.regClose,
    ...overrides,
  };
}

function buildEvent(overrides: Partial<EventWithConfig> = {}): EventWithConfig {
  const windows = defaultWindows();
  return {
    id: "00000000-0000-0000-0000-000000000010",
    organizationId: "00000000-0000-0000-0000-000000000001",
    name: "Workshop",
    description: "Test event",
    location: "Room A",
    state: "Draft",
    startAt: windows.open,
    endAt: windows.close,
    createdBy: "00000000-0000-0000-0000-000000000099",
    updatedBy: "00000000-0000-0000-0000-000000000099",
    createdAt: windows.regOpen,
    updatedAt: windows.regOpen,
    version: 1,
    ruleConfig: {
      eventId: "00000000-0000-0000-0000-000000000010",
      capacity: 10,
      waitlistEnabled: false,
      registrationOpenAt: windows.regOpen,
      registrationCloseAt: windows.regClose,
      checkinOpenAt: windows.regOpen,
      checkinCloseAt: windows.regClose,
      feedbackRequired: false,
      feedbackOpenAt: windows.regOpen,
      feedbackCloseAt: windows.regClose,
      registrationPaused: false,
      version: 1,
      ...overrides.ruleConfig,
    },
    ...overrides,
  };
}

describe("event validation", () => {
  it("validateRuleConfig rejects inverted registration window", () => {
    const windows = defaultWindows();
    assert.throws(
      () =>
        validateRuleConfig(
          buildRuleConfig({
            registrationOpenAt: windows.regClose,
            registrationCloseAt: windows.regOpen,
          }),
        ),
      (error: unknown) =>
        error instanceof ApiError && error.statusCode === 422,
    );
  });

  it("validateCreateInput requires name and valid schedule", () => {
    const windows = defaultWindows();
    assert.throws(
      () =>
        validateCreateInput({
          name: "  ",
          startAt: windows.open,
          endAt: windows.close,
          ruleConfig: buildRuleConfig(),
        }),
      (error: unknown) =>
        error instanceof ApiError && error.code === "INVALID_INPUT",
    );

    assert.throws(
      () =>
        validateCreateInput({
          name: "Valid",
          startAt: windows.close,
          endAt: windows.open,
          ruleConfig: buildRuleConfig(),
        }),
      (error: unknown) =>
        error instanceof ApiError && error.statusCode === 422,
    );
  });

  it("assertPublishReady rejects incomplete required fields", () => {
    assert.throws(
      () => assertPublishReady(buildEvent({ location: "" })),
      (error: unknown) =>
        error instanceof ApiError && error.statusCode === 422,
    );
  });

  it("resolveTransition allows publish from Draft and rejects illegal transitions", () => {
    assert.equal(resolveTransition("Draft", "publishEvent"), "Published");
    assert.throws(
      () => resolveTransition("Draft", "startEvent"),
      (error: unknown) =>
        error instanceof ApiError &&
        error.code === "INVALID_STATE_TRANSITION",
    );
  });

  it("validateUpdateInput requires audit reason for critical rule changes after registration opens", () => {
    const event = buildEvent({ state: "RegistrationOpen" });
    assert.throws(
      () =>
        validateUpdateInput(event, {
          ruleConfig: { capacity: 20 },
        }),
      (error: unknown) =>
        error instanceof ApiError &&
        error.code === VALIDATION_ERROR_CODES.AUDIT_REQUIRED_FOR_CRITICAL_CHANGE,
    );

    assert.doesNotThrow(() =>
      validateUpdateInput(event, {
        ruleConfig: { capacity: 20 },
        reasonCode: "CAPACITY_INCREASE",
        reasonText: "Higher demand",
      }),
    );
  });

  it("validateUpdateInput forbids non-critical rule changes after registration opens", () => {
    const event = buildEvent({ state: "RegistrationOpen" });
    assert.throws(
      () =>
        validateUpdateInput(event, {
          ruleConfig: { registrationPaused: true },
        }),
      (error: unknown) =>
        error instanceof ApiError &&
        error.code === VALIDATION_ERROR_CODES.EVENT_RULE_CHANGE_FORBIDDEN,
    );
  });
});
