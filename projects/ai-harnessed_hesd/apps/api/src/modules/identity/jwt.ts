import { SignJWT, jwtVerify } from "jose";
import type { Role } from "./types.js";

const DEFAULT_EXPIRY_SECONDS = 3600;

export interface AccessTokenClaims {
  sub: string;
  email: string;
  roles: Role[];
}

function getSecret(): Uint8Array {
  const secret = process.env.JWT_SECRET ?? "local-dev-secret-change-me";
  return new TextEncoder().encode(secret);
}

export async function signAccessToken(
  claims: AccessTokenClaims,
  expiresInSeconds = DEFAULT_EXPIRY_SECONDS,
): Promise<string> {
  return new SignJWT({ email: claims.email, roles: claims.roles })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(claims.sub)
    .setIssuedAt()
    .setExpirationTime(`${expiresInSeconds}s`)
    .sign(getSecret());
}

export async function verifyAccessToken(token: string): Promise<AccessTokenClaims> {
  const { payload } = await jwtVerify(token, getSecret(), { algorithms: ["HS256"] });
  const sub = payload.sub;
  if (!sub) {
    throw new Error("Invalid token subject");
  }
  const email = typeof payload.email === "string" ? payload.email : "";
  const roles = Array.isArray(payload.roles)
    ? (payload.roles.filter((r): r is Role => typeof r === "string") as Role[])
    : [];
  return { sub, email, roles };
}

export function accessTokenExpirySeconds(): number {
  return DEFAULT_EXPIRY_SECONDS;
}
