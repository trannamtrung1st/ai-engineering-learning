import type { ScheduleTemplate } from "./types.js";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const DAY_OF_WEEK: Record<string, number> = {
  Sunday: 0,
  Monday: 1,
  Tuesday: 2,
  Wednesday: 3,
  Thursday: 4,
  Friday: 5,
  Saturday: 6,
};

export function isUuid(value: string | undefined): value is string {
  return typeof value === "string" && UUID_RE.test(value);
}

export function validateTermDates(startDate: string, endDate: string): boolean {
  if (!startDate || !endDate) return false;
  return endDate >= startDate;
}

export function validateScheduleTemplate(template: ScheduleTemplate | undefined): string | null {
  if (!template) return null;
  if (!DAY_OF_WEEK[template.dayOfWeek]) {
    return "Invalid dayOfWeek";
  }
  if (!/^\d{2}:\d{2}$/.test(template.startTime)) {
    return "Invalid startTime";
  }
  if (!Number.isFinite(template.durationMinutes) || template.durationMinutes <= 0) {
    return "Invalid durationMinutes";
  }
  return null;
}

export function datesForDayOfWeek(
  startDate: string,
  endDate: string,
  dayOfWeek: string,
): string[] {
  const targetDay = DAY_OF_WEEK[dayOfWeek];
  if (targetDay === undefined) return [];

  const dates: string[] = [];
  const cursor = new Date(`${startDate}T00:00:00.000Z`);
  const end = new Date(`${endDate}T00:00:00.000Z`);

  while (cursor.getUTCDay() !== targetDay && cursor <= end) {
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }

  while (cursor <= end) {
    dates.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 7);
  }

  return dates;
}

export function sessionTimesForDate(
  date: string,
  startTime: string,
  durationMinutes: number,
): { scheduledStartAt: Date; scheduledEndAt: Date } {
  const scheduledStartAt = new Date(`${date}T${startTime}:00.000Z`);
  const scheduledEndAt = new Date(scheduledStartAt.getTime() + durationMinutes * 60_000);
  return { scheduledStartAt, scheduledEndAt };
}

/** FR-17 / BR-06 — active enrollment lookup for check-in eligibility. */
export async function isStudentEnrolled(
  query: (sql: string, params?: unknown[]) => Promise<{ rows: { enrolled: boolean }[] }>,
  studentUserId: string,
  classSectionId: string,
): Promise<boolean> {
  const result = await query(
    `
    SELECT EXISTS (
      SELECT 1
      FROM enrollments
      WHERE class_section_id = $1
        AND student_user_id = $2
        AND status = 'Active'
    ) AS enrolled
    `,
    [classSectionId, studentUserId],
  );
  return result.rows[0]?.enrolled === true;
}
