import { ErrorCode, UserRole } from "@wecheck/domain";
import type { DbPool } from "../../../infra/db.js";
import type { SessionStore } from "../../../auth/session-store.js";
import type { AuthSession } from "../../../auth/types.js";
import {
  setupAlreadyComplete,
  validationFailed,
} from "../../../errors/api-error.js";
import { hashPassword } from "../password-hasher.js";
import {
  isUniqueViolation,
  uniqueFieldFromError,
  UserRepository,
} from "../user-repository.js";
import type { FirstAdminInput, UserDto } from "../types.js";
import { toUserDto } from "../types.js";

/** Advisory xact lock key for one-time bootstrap (distinct from integration-test lock). */
const BOOTSTRAP_LOCK_KEY = 0x53534554;

export interface SetupStatus {
  needsSetup: boolean;
}

export interface CreateFirstAdminResult {
  user: UserDto;
  session: AuthSession;
}

export class SetupService {
  constructor(
    private readonly db: DbPool,
    private readonly users: UserRepository,
    private readonly sessions: SessionStore,
  ) {}

  async getStatus(): Promise<SetupStatus> {
    const count = await this.users.count();
    return { needsSetup: count === 0 };
  }

  async createFirstAdmin(input: FirstAdminInput): Promise<CreateFirstAdminResult> {
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      await client.query("SELECT pg_advisory_xact_lock($1)", [BOOTSTRAP_LOCK_KEY]);

      const count = await this.users.countOnClient(client);
      if (count > 0) {
        throw setupAlreadyComplete();
      }

      const passwordHash = await hashPassword(input.password);
      const inactivityHours = await this.sessions.getInactivityHours();

      let user;
      try {
        user = await this.users.createOnClient(client, {
          institutionalId: input.institutionalId,
          displayName: input.displayName,
          email: input.email,
          passwordHash,
          role: UserRole.TrainingOfficeAdmin,
          active: true,
        });
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

      const session = await this.sessions.createSessionOnClient(
        client,
        user.id,
        inactivityHours,
      );

      await this.users.writeAuditLogOnClient(client, {
        userId: user.id,
        actorId: user.id,
        action: "bootstrap_first_admin",
        reason: "First deployment bootstrap",
      });

      await client.query("COMMIT");
      return { user: toUserDto(user), session };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }
}
