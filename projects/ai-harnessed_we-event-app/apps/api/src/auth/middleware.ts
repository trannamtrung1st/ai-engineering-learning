import type { FastifyRequest } from "fastify";
import { ApiError } from "../errors/api-error.js";
import { assertRolePermission, type Capability } from "./permissions.js";
import type { ActorRole, JwtPayload } from "./types.js";

export async function requireAuth(request: FastifyRequest): Promise<void> {
  try {
    await request.jwtVerify<JwtPayload>();
  } catch {
    throw new ApiError({
      code: "UNAUTHENTICATED",
      message: "Authentication required.",
      statusCode: 401,
    });
  }
}

export function requireRole(...roles: ActorRole[]) {
  return async (request: FastifyRequest): Promise<void> => {
    const actor = getActor(request);
    if (!roles.includes(actor.role)) {
      throw new ApiError({
        code: "FORBIDDEN",
        message: "You do not have permission to perform this action.",
        statusCode: 403,
        details: { role: actor.role, allowedRoles: roles },
      });
    }
  };
}

export function requireCapability(capability: Capability) {
  return async (request: FastifyRequest): Promise<void> => {
    assertRolePermission(getActor(request), capability);
  };
}

export function getActor(request: FastifyRequest): JwtPayload {
  const actor = request.user;
  if (!actor) {
    throw new ApiError({
      code: "UNAUTHENTICATED",
      message: "Authentication required.",
      statusCode: 401,
    });
  }
  return actor;
}
