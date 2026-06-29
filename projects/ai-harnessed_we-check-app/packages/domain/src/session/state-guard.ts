import { SessionStatus } from "../enums.js";

export type SessionTransitionEvent = "open" | "close" | "cancel";

const SESSION_TRANSITIONS: Readonly<
  Record<SessionStatus, ReadonlySet<SessionTransitionEvent>>
> = {
  [SessionStatus.Draft]: new Set(["open", "cancel"]),
  [SessionStatus.Active]: new Set(["close"]),
  [SessionStatus.Closed]: new Set(),
  [SessionStatus.Cancelled]: new Set(),
};

/** SM-01 — legal session lifecycle transitions. */
export function canTransitionSession(
  from: SessionStatus,
  event: SessionTransitionEvent,
): boolean {
  return SESSION_TRANSITIONS[from].has(event);
}

export function getSessionStatusAfterTransition(
  from: SessionStatus,
  event: SessionTransitionEvent,
): SessionStatus {
  if (!canTransitionSession(from, event)) {
    throw new InvalidSessionTransitionError(from, event);
  }
  switch (event) {
    case "open":
      return SessionStatus.Active;
    case "close":
      return SessionStatus.Closed;
    case "cancel":
      return SessionStatus.Cancelled;
  }
}

export class InvalidSessionTransitionError extends Error {
  readonly code = "InvalidSessionState" as const;

  constructor(
    public readonly from: SessionStatus,
    public readonly event: SessionTransitionEvent,
  ) {
    super(`Invalid session transition: ${from} --${event}-->`);
    this.name = "InvalidSessionTransitionError";
  }
}

export interface RoomGpsInput {
  roomLatitude: number | null;
  roomLongitude: number | null;
}

/** BR-07 — room GPS required before Draft → Active. */
export function hasValidRoomGps(input: RoomGpsInput): boolean {
  const { roomLatitude, roomLongitude } = input;
  if (roomLatitude === null || roomLongitude === null) {
    return false;
  }
  return (
    Number.isFinite(roomLatitude) &&
    Number.isFinite(roomLongitude) &&
    roomLatitude >= -90 &&
    roomLatitude <= 90 &&
    roomLongitude >= -180 &&
    roomLongitude <= 180
  );
}
