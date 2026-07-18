import { eq } from "drizzle-orm";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createDatabase } from "./client";
import { DEMO, seedDatabase } from "./seed";
import { classSections, classSessions, enrollments, users } from "./schema";

describe("demo seed", () => {
  let database: ReturnType<typeof createDatabase>;

  beforeEach(() => {
    database = createDatabase(":memory:");
    seedDatabase(database.db, database.sqlite);
  });

  afterEach(() => database.sqlite.close());

  it("creates the minimum complete demo path", () => {
    const lecturer = database.db
      .select()
      .from(users)
      .where(eq(users.id, DEMO.lecturerId))
      .get();
    const students = database.db.select().from(enrollments).all();
    const section = database.db.select().from(classSections).get();
    const session = database.db.select().from(classSessions).get();

    expect(lecturer?.role).toBe("lecturer");
    expect(students.map(({ studentId }) => studentId)).toEqual(
      expect.arrayContaining([...DEMO.enrolledStudentIds]),
    );
    expect(section?.lecturerId).toBe(DEMO.lecturerId);
    expect(session?.classSectionId).toBe(DEMO.classSectionId);
  });

  it("keeps a student outside the demo section", () => {
    const enrollment = database.db
      .select()
      .from(enrollments)
      .where(eq(enrollments.studentId, DEMO.nonEnrolledStudentId))
      .get();

    expect(enrollment).toBeUndefined();
  });
});
