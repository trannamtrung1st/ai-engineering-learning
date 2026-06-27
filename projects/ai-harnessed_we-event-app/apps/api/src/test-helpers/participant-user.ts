import type { ActorRole } from "@we-event/domain";
import { resolveActorId } from "../auth/resolve-actor-id.js";
import { TEST_PASSWORD_HASH } from "../modules/auth/password.js";
import {
  ensureParticipantUser,
  ensureUserSchema,
  provisionTestUser,
} from "../modules/user/repository.js";

const DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001";

export async function ensureTestParticipant(
  userIdOrSub: string,
): Promise<string> {
  const userId = resolveActorId(userIdOrSub);
  await ensureUserSchema();
  await ensureParticipantUser(userId, "Test Participant", TEST_PASSWORD_HASH);
  return userId;
}

export async function ensureTestOrganizerAdmin(
  userId = "00000000-0000-0000-0000-000000000099",
): Promise<string> {
  await ensureUserSchema();
  await provisionTestUser(
    userId,
    "OrganizerAdmin",
    "Organizer Admin",
    TEST_PASSWORD_HASH,
    { organizationId: DEFAULT_ORG_ID },
  );
  return userId;
}

export async function ensureTestUser(
  userIdOrSub: string,
  role: ActorRole = "Participant",
  options: {
    organizationId?: string | null;
    assignedEventIds?: string[];
  } = {},
): Promise<string> {
  const userId = resolveActorId(userIdOrSub);
  await ensureUserSchema();

  if (role === "Participant") {
    await ensureParticipantUser(userId, "Test Participant", TEST_PASSWORD_HASH);
    return userId;
  }

  await provisionTestUser(
    userId,
    role,
    `Test ${role}`,
    TEST_PASSWORD_HASH,
    {
      organizationId: options.organizationId ?? DEFAULT_ORG_ID,
      assignedEventIds: options.assignedEventIds,
    },
  );
  return userId;
}
