import {
  SESSION_INACTIVITY_DEFAULT_HOURS,
  SESSION_INACTIVITY_MAX_HOURS,
  SESSION_INACTIVITY_MIN_HOURS,
} from "@wecheck/domain";
import { nowMs } from "../infra/clock.js";

export const POLICY_KEY_SESSION_INACTIVITY = "session_inactivity_hours";

export function inactivityMsFromHours(hours: number): number {
  return hours * 60 * 60 * 1000;
}

export function parseInactivityHours(raw: string): number {
  const parsed = Number.parseInt(raw, 10);
  if (
    Number.isNaN(parsed) ||
    parsed < SESSION_INACTIVITY_MIN_HOURS ||
    parsed > SESSION_INACTIVITY_MAX_HOURS
  ) {
    return SESSION_INACTIVITY_DEFAULT_HOURS;
  }
  return parsed;
}

export function computeExpiresAt(
  lastActivityAt: Date,
  inactivityHours: number,
): Date {
  return new Date(
    lastActivityAt.getTime() + inactivityMsFromHours(inactivityHours),
  );
}

export function isSessionExpired(
  lastActivityAt: Date,
  inactivityHours: number,
  at: Date = new Date(nowMs()),
): boolean {
  return at.getTime() - lastActivityAt.getTime() >= inactivityMsFromHours(inactivityHours);
}
