import type { UserRole } from "@wecheck/domain";

export interface AuthUser {
  id: string;
  institutionalId: string;
  displayName: string;
  email: string;
  role: UserRole;
  active: boolean;
}

export interface AuthSession {
  id: string;
  userId: string;
  expiresAt: Date;
  lastActivityAt: Date;
}

export interface AuthContext {
  session: AuthSession;
  user: AuthUser;
}

declare module "fastify" {
  interface FastifyRequest {
    requestId: string;
    auth?: AuthContext;
  }
}
