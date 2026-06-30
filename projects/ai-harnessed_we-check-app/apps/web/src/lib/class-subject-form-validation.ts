import { classSubjectCopy } from "@/lib/copy/class-subject-labels";

/** Uppercase alphanumeric + hyphen per validation rules §3.2a */
export const REFERENCE_CODE_RE = /^[A-Z0-9-]{2,16}$/;

export interface ClassSubjectFormValues {
  classCode: string;
  className: string;
  subjectCode: string;
  subjectName: string;
}

export function normalizeReferenceCode(value: string): string {
  return value.trim().toUpperCase();
}

export function validateClassSubjectForm(
  values: ClassSubjectFormValues,
): Record<string, string> {
  const errors: Record<string, string> = {};

  const classCode = normalizeReferenceCode(values.classCode);
  if (!classCode) {
    errors.classCode = classSubjectCopy.requiredField;
  } else if (!REFERENCE_CODE_RE.test(classCode)) {
    errors.classCode = classSubjectCopy.invalidFormat;
  }

  const className = values.className.trim();
  if (!className || className.length > 200) {
    errors.className = classSubjectCopy.invalidLength;
  }

  const subjectCode = normalizeReferenceCode(values.subjectCode);
  if (!subjectCode) {
    errors.subjectCode = classSubjectCopy.requiredField;
  } else if (!REFERENCE_CODE_RE.test(subjectCode)) {
    errors.subjectCode = classSubjectCopy.invalidFormat;
  }

  const subjectName = values.subjectName.trim();
  if (!subjectName || subjectName.length > 200) {
    errors.subjectName = classSubjectCopy.invalidLength;
  }

  return errors;
}
