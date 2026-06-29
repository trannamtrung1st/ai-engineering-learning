import { apiFetch } from "@/lib/api-client";

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
