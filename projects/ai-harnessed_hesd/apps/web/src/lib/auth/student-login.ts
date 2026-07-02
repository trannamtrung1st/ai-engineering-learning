const STUDENT_CODE_EMAIL: Record<string, string> = {
  SV001: "student1@attendly.local",
  SV002: "student2@attendly.local",
  SV003: "student3@attendly.local",
};

/** Map institution student code to seed email; pass through values that already look like email. */
export function resolveStudentEmail(studentIdOrEmail: string): string {
  const trimmed = studentIdOrEmail.trim();
  if (trimmed.includes("@")) {
    return trimmed.toLowerCase();
  }
  const mapped = STUDENT_CODE_EMAIL[trimmed.toUpperCase()];
  return mapped ?? trimmed.toLowerCase();
}
