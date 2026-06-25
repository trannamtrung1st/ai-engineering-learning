export {
  assignUserRole,
  createUser,
  createUserWithRole,
  ensureParticipantUser,
  ensureUserSchema,
  findUserByEmail,
  findUserById,
  findUserPasswordHashByEmail,
  listUserRoles,
  toUserProfile,
} from "./repository.js";
export type {
  CreateUserInput,
  UserProfile,
  UserRoleAssignment,
  UserRoleRow,
  UserRow,
} from "./types.js";
