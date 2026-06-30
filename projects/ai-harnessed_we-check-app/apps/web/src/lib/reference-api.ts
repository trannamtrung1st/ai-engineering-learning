import {
  apiFetch,
  type ApiErrorBody,
} from "@/lib/api-client";

export interface ClassItem {
  id: string;
  code: string;
  name: string;
  term: string | null;
}

export interface SubjectItem {
  id: string;
  code: string;
  name: string;
}

export type ReferenceMutationResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; error: ApiErrorBody };

export function mapReferenceApiErrorToFieldErrors(
  error: ApiErrorBody,
): Record<string, string> {
  if (error.errorCode === "DuplicateClassCode") {
    return { classCode: error.message ?? "Mã lớp đã tồn tại" };
  }
  if (error.errorCode === "DuplicateSubjectCode") {
    return { subjectCode: error.message ?? "Mã môn học đã tồn tại" };
  }
  const map: Record<string, string> = {};
  for (const detail of error.details ?? []) {
    const field =
      detail.field === "code"
        ? detail.code === "DuplicateSubjectCode"
          ? "subjectCode"
          : "classCode"
        : detail.field === "name"
          ? detail.field
          : detail.field;
    map[field] = detail.message;
  }
  return map;
}

export async function fetchClasses(): Promise<ClassItem[]> {
  const res = await apiFetch<{ items: ClassItem[] }>("/classes");
  if (!res.ok) {
    throw new Error(res.data.errorCode ?? "ClassesFetchFailed");
  }
  return res.data.items;
}

export async function fetchSubjects(): Promise<SubjectItem[]> {
  const res = await apiFetch<{ items: SubjectItem[] }>("/subjects");
  if (!res.ok) {
    throw new Error(res.data.errorCode ?? "SubjectsFetchFailed");
  }
  return res.data.items;
}

/** FR-03 / AC-03d — create class reference record */
export async function createClass(payload: {
  code: string;
  name: string;
}): Promise<ReferenceMutationResult<ClassItem>> {
  const res = await apiFetch<ClassItem>("/classes", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  return { ok: true, data: res.data };
}

/** FR-03 / AC-03d — create subject reference record */
export async function createSubject(payload: {
  code: string;
  name: string;
}): Promise<ReferenceMutationResult<SubjectItem>> {
  const res = await apiFetch<SubjectItem>("/subjects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  return { ok: true, data: res.data };
}
