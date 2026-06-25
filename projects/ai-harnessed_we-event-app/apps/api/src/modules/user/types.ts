import type { ActorRole } from "@we-event/domain";

export interface UserRow {
  id: string;
  email: string;
  displayName: string;
  createdAt: string;
  updatedAt: string;
}

export interface UserRoleRow {
  id: string;
  userId: string;
  role: ActorRole;
  organizationId: string | null;
  assignedEventIds: string[];
}

export interface UserProfile {
  userId: string;
  email: string;
  displayName: string;
  roles: UserRoleAssignment[];
}

export interface UserRoleAssignment {
  role: ActorRole;
  organizationId: string | null;
  assignedEventIds: string[];
}

export interface CreateUserInput {
  email: string;
  passwordHash: string;
  displayName: string;
}
