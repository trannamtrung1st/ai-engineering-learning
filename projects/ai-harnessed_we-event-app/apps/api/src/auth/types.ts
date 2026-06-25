import type { ActorRole } from "@we-event/domain";

export type { ActorRole };
export { ACTOR_ROLES } from "@we-event/domain";

export interface JwtPayload {
  sub: string;
  role: ActorRole;
  assignedEventIds?: string[];
}
