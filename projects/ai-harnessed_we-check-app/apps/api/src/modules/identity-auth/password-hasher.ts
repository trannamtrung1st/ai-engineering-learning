import bcrypt from "bcrypt";

const BCRYPT_ROUNDS = 12;

const BCRYPT_PATTERN = /^\$2[aby]\$/;
const ARGON2_PATTERN = /^\$argon2/;

export function isPasswordHash(value: string): boolean {
  return BCRYPT_PATTERN.test(value) || ARGON2_PATTERN.test(value);
}

export async function hashPassword(plaintext: string): Promise<string> {
  return bcrypt.hash(plaintext, BCRYPT_ROUNDS);
}

export async function verifyPassword(
  plaintext: string,
  passwordHash: string,
): Promise<boolean> {
  if (!passwordHash || !isPasswordHash(passwordHash)) {
    return false;
  }
  return bcrypt.compare(plaintext, passwordHash);
}
