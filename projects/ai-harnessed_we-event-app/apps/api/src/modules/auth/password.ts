import bcrypt from "bcrypt";

const BCRYPT_ROUNDS = 10;

export async function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, BCRYPT_ROUNDS);
}

export async function verifyPassword(
  password: string,
  passwordHash: string,
): Promise<boolean> {
  return bcrypt.compare(password, passwordHash);
}

/** Fixed hash for integration test fixtures (password: "test-password"). */
export const TEST_PASSWORD_HASH =
  "$2b$10$ZLvMEXurERIwVQwHCd78EOwF6NwZ6HY.TV24xG/AHtq0031vuC8G.";
