import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createDatabase } from "../db/client";
import { DEMO, seedDatabase } from "../db/seed";
import {
  authenticate,
  createSessionToken,
  verifySessionToken,
} from "./session";

describe("session authentication", () => {
  let database: ReturnType<typeof createDatabase>;

  beforeEach(() => {
    process.env.SESSION_SECRET = "test-session-secret";
    database = createDatabase(":memory:");
    seedDatabase(database.db, database.sqlite);
  });

  afterEach(() => database.sqlite.close());

  it("authenticates seeded students and lecturers", () => {
    expect(
      authenticate(database.db, "ada@attendly.test", DEMO.password),
    ).toMatchObject({ userId: DEMO.lecturerId, role: "lecturer" });
    expect(
      authenticate(database.db, "linh@attendly.test", DEMO.password),
    ).toMatchObject({ userId: DEMO.enrolledStudentIds[0], role: "student" });
  });

  it("rejects invalid credentials", () => {
    expect(
      authenticate(database.db, "linh@attendly.test", "wrong"),
    ).toBeNull();
  });

  it("signs, verifies, and expires a session", () => {
    const now = Date.now();
    const token = createSessionToken(
      { userId: DEMO.enrolledStudentIds[0], role: "student" },
      now,
    );

    expect(verifySessionToken(token, now)).toMatchObject({
      userId: DEMO.enrolledStudentIds[0],
      role: "student",
    });
    expect(verifySessionToken(token, now + 9 * 60 * 60 * 1000)).toBeNull();
    expect(verifySessionToken(`${token}tampered`, now)).toBeNull();
  });

  it("treats a missing cookie as unauthenticated", () => {
    expect(verifySessionToken(undefined)).toBeNull();
  });
});
