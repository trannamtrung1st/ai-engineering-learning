import { ErrorCode } from "@wecheck/domain";
import { notFound, validationFailed } from "../../errors/api-error.js";
import type { SessionStore } from "../../auth/session-store.js";
import { hashPassword } from "./password-hasher.js";
import {
  isUniqueViolation,
  uniqueFieldFromError,
  UserRepository,
} from "./user-repository.js";
import type { CreateUserInput, UpdateUserInput, UserDto, UserRecord } from "./types.js";
import { toUserDto } from "./types.js";

export class UserService {
  constructor(
    private readonly users: UserRepository,
    private readonly sessions: SessionStore,
  ) {}

  async provision(input: CreateUserInput): Promise<UserDto> {
    const passwordHash = await hashPassword(input.password);
    try {
      const user = await this.users.create({ ...input, passwordHash });
      return toUserDto(user);
    } catch (error) {
      if (isUniqueViolation(error)) {
        const field = uniqueFieldFromError(error) ?? "institutionalId";
        throw validationFailed([
          {
            field,
            code: ErrorCode.ValidationFailed,
            message:
              field === "email"
                ? "Email đã tồn tại"
                : "Mã định danh đã tồn tại",
          },
        ]);
      }
      throw error;
    }
  }

  async update(
    userId: string,
    input: UpdateUserInput,
    actorId: string,
  ): Promise<UserDto> {
    const existing = await this.users.findById(userId);
    if (!existing) {
      throw notFound();
    }

    const fields: {
      institutionalId?: string;
      displayName?: string;
      email?: string;
      passwordHash?: string;
      role?: UserRecord["role"];
      active?: boolean;
    } = {};

    if (input.institutionalId !== undefined) {
      fields.institutionalId = input.institutionalId;
    }
    if (input.displayName !== undefined) {
      fields.displayName = input.displayName;
    }
    if (input.email !== undefined) {
      fields.email = input.email;
    }
    if (input.role !== undefined) {
      fields.role = input.role;
    }
    if (input.password !== undefined) {
      fields.passwordHash = await hashPassword(input.password);
    }
    if (input.active !== undefined) {
      fields.active = input.active;
    }

    try {
      const updated = await this.users.update(userId, fields);
      if (!updated) {
        throw notFound();
      }

      if (input.active === false && existing.active) {
        await this.sessions.revokeAllSessionsForUser(userId);
        await this.users.writeAuditLog({
          userId,
          actorId,
          action: "deactivate",
          reason: "Admin deactivated account",
        });
      } else if (input.active === true && !existing.active) {
        await this.users.writeAuditLog({
          userId,
          actorId,
          action: "reactivate",
          reason: "Admin reactivated account",
        });
      }

      if (input.password !== undefined) {
        await this.users.writeAuditLog({
          userId,
          actorId,
          action: "password_change",
          reason: "Admin reset password",
        });
      }

      return toUserDto(updated);
    } catch (error) {
      if (isUniqueViolation(error)) {
        const field = uniqueFieldFromError(error) ?? "institutionalId";
        throw validationFailed([
          {
            field,
            code: ErrorCode.ValidationFailed,
            message:
              field === "email"
                ? "Email đã tồn tại"
                : "Mã định danh đã tồn tại",
          },
        ]);
      }
      throw error;
    }
  }

  async list(options: {
    role?: UserRecord["role"];
    active?: boolean;
    search?: string;
    limit: number;
    cursor?: string;
  }): Promise<{ items: UserDto[]; nextCursor: string | null }> {
    const result = await this.users.list(options);
    return {
      items: result.items.map(toUserDto),
      nextCursor: result.nextCursor,
    };
  }
}
