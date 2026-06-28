import {
  accountDeactivated,
  invalidCredentials,
  sessionExpired,
  unauthenticated,
} from "../../errors/api-error.js";
import type { SessionStore } from "../../auth/session-store.js";
import type { AuthSession, AuthUser } from "../../auth/types.js";
import { verifyPassword } from "./password-hasher.js";
import { UserRepository } from "./user-repository.js";
import type { LoginInput } from "./types.js";

export interface AuthenticateResult {
  user: AuthUser;
  session: AuthSession;
  redirectTo?: string;
}

export class AuthService {
  constructor(
    private readonly users: UserRepository,
    private readonly sessions: SessionStore,
  ) {}

  async authenticate(input: LoginInput): Promise<AuthenticateResult> {
    const user = await this.users.findByEmail(input.email);
    if (!user) {
      throw invalidCredentials();
    }
    if (!user.active) {
      throw accountDeactivated();
    }
    const valid = await verifyPassword(input.password, user.passwordHash);
    if (!valid) {
      throw invalidCredentials();
    }

    const session = await this.sessions.createSession(user.id);
    return {
      user: {
        id: user.id,
        institutionalId: user.institutionalId,
        displayName: user.displayName,
        email: user.email,
        role: user.role,
        active: user.active,
      },
      session,
      redirectTo: input.returnUrl,
    };
  }

  async requireUser(sessionId: string): Promise<{ session: AuthSession; user: AuthUser }> {
    const resolved = await this.sessions.resolveSession(sessionId);
    if (!resolved.ok) {
      if (resolved.reason === "expired") {
        throw sessionExpired();
      }
      throw unauthenticated();
    }
    return { session: resolved.session, user: resolved.user };
  }

  async logout(sessionId: string): Promise<void> {
    await this.sessions.revokeSession(sessionId);
  }
}
