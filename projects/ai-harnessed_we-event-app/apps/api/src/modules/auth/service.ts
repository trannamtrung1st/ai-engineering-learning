import type { FastifyReply } from "fastify";
import type { JwtPayload } from "../../auth/types.js";
import { ApiError } from "../../errors/api-error.js";
import {
  createUserWithRole,
  ensureUserSchema,
  findUserPasswordHashByEmail,
  listUserRoles,
  toUserProfile,
} from "../user/repository.js";
import type { UserProfile, UserRow } from "../user/types.js";
import { hashPassword, verifyPassword } from "./password.js";
import {
  selectJwtRole,
  validateLoginInput,
  validateRegisterInput,
  type LoginInput,
  type RegisterInput,
} from "./validation.js";

export interface AuthSession {
  token: string;
  profile: UserProfile;
}

export class AuthService {
  async register(
    input: RegisterInput,
    signToken: (payload: JwtPayload) => Promise<string>,
  ): Promise<AuthSession> {
    await ensureUserSchema();
    const validated = validateRegisterInput(input);
    const passwordHash = await hashPassword(validated.password);
    const { user, roles } = await createUserWithRole(
      {
        email: validated.email,
        passwordHash,
        displayName: validated.displayName,
      },
      "Participant",
    );
    return this.buildSession(user, roles, signToken);
  }

  async login(
    input: LoginInput,
    signToken: (payload: JwtPayload) => Promise<string>,
  ): Promise<AuthSession> {
    await ensureUserSchema();
    const validated = validateLoginInput(input);
    const record = await findUserPasswordHashByEmail(validated.email);
    if (!record) {
      throw new ApiError({
        code: "INVALID_CREDENTIALS",
        message: "Invalid email or password.",
        statusCode: 401,
      });
    }

    const valid = await verifyPassword(validated.password, record.passwordHash);
    if (!valid) {
      throw new ApiError({
        code: "INVALID_CREDENTIALS",
        message: "Invalid email or password.",
        statusCode: 401,
      });
    }

    const roles = await listUserRoles(record.user.id);
    return this.buildSession(record.user, roles, signToken);
  }

  async buildSession(
    user: UserRow,
    roles: Awaited<ReturnType<typeof listUserRoles>>,
    signToken: (payload: JwtPayload) => Promise<string>,
  ): Promise<AuthSession> {
    const profile = toUserProfile(user, roles);
    const { role, assignedEventIds } = selectJwtRole(roles);
    const token = await signToken({
      sub: user.id,
      role,
      assignedEventIds,
    });
    return { token, profile };
  }
}

export const authService = new AuthService();

export async function signAuthToken(
  reply: FastifyReply,
  payload: JwtPayload,
): Promise<string> {
  return reply.jwtSign(payload);
}
