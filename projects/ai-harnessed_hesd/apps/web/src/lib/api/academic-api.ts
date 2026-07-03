import type { ApiEnvelope } from "@attendly/domain";
import { apiRequest } from "./client.js";

export interface TermSummary {
  id: string;
  code: string;
  name: string;
  startDate: string;
  endDate: string;
  isActive: boolean;
}

export interface CourseSummary {
  id: string;
  code: string;
  name: string;
  facultyId: string;
  creditUnits: number | null;
  isActive: boolean;
}

export interface RoomSummary {
  id: string;
  code: string;
  name: string;
  building: string | null;
  isActive: boolean;
}

export interface ClassSectionSummary {
  id: string;
  sectionCode: string;
  termId: string;
  courseId: string;
  lecturerUserId: string;
  defaultRoomId: string | null;
  capacity: number | null;
  isActive: boolean;
}

export interface ScheduleTemplateInput {
  dayOfWeek: string;
  startTime: string;
  durationMinutes: number;
}

export interface EnrollmentImportRejectedRow {
  rowNumber: number;
  code: string;
  message: string;
}

export interface EnrollmentImportData {
  classSectionId: string;
  acceptedRows: number;
  rejectedRows: EnrollmentImportRejectedRow[];
}

export interface PaginationMeta {
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
}

export interface CreateTermInput {
  code: string;
  name: string;
  startDate: string;
  endDate: string;
  isActive: boolean;
}

export interface CreateClassSectionInput {
  sectionCode: string;
  termId: string;
  courseId: string;
  lecturerUserId: string;
  defaultRoomId?: string;
  capacity?: number;
  scheduleTemplate?: ScheduleTemplateInput;
}

export interface CreateClassSectionData extends ClassSectionSummary {
  generatedSessionCount?: number;
}

type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; code: string; message: string };

type ListResult<T> =
  | { ok: true; items: T[]; pagination: PaginationMeta }
  | { ok: false; code: string; message: string };

function readPagination(meta: ApiEnvelope<unknown>["meta"]): PaginationMeta {
  const pagination = (
    meta as ApiEnvelope<unknown>["meta"] & { pagination?: PaginationMeta }
  ).pagination;
  return {
    page: pagination?.page ?? 1,
    pageSize: pagination?.pageSize ?? 25,
    totalItems: pagination?.totalItems ?? 0,
    totalPages: pagination?.totalPages ?? 0,
  };
}

function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export async function fetchTerms(params: {
  page?: number;
  pageSize?: number;
  activeOnly?: boolean;
  search?: string;
}): Promise<ListResult<TermSummary>> {
  const query = new URLSearchParams();
  query.set("page", String(params.page ?? 1));
  query.set("pageSize", String(params.pageSize ?? 25));
  if (params.activeOnly) query.set("activeOnly", "true");

  const envelope = await apiRequest<TermSummary[]>(`/terms?${query.toString()}`);
  if (envelope.data && !envelope.error) {
    let items = envelope.data;
    if (params.search?.trim()) {
      const needle = params.search.trim().toLowerCase();
      items = items.filter(
        (term) =>
          term.code.toLowerCase().includes(needle) || term.name.toLowerCase().includes(needle),
      );
    }
    return {
      ok: true,
      items,
      pagination: readPagination(envelope.meta),
    };
  }
  return {
    ok: false,
    code: envelope.error?.code ?? "RequestFailed",
    message: envelope.error?.message ?? "Không thể tải danh sách học kỳ.",
  };
}

export async function createTerm(input: CreateTermInput): Promise<ApiResult<TermSummary>> {
  const envelope = await apiRequest<TermSummary>("/terms", {
    method: "POST",
    body: input,
    idempotencyKey: newIdempotencyKey(),
  });
  if (envelope.data && !envelope.error) {
    return { ok: true, data: envelope.data };
  }
  return {
    ok: false,
    code: envelope.error?.code ?? "CreateFailed",
    message: envelope.error?.message ?? "Không thể tạo học kỳ.",
  };
}

export async function fetchCourses(params?: {
  page?: number;
  pageSize?: number;
}): Promise<ListResult<CourseSummary>> {
  const query = new URLSearchParams();
  query.set("page", String(params?.page ?? 1));
  query.set("pageSize", String(params?.pageSize ?? 100));

  const envelope = await apiRequest<CourseSummary[]>(`/courses?${query.toString()}`);
  if (envelope.data && !envelope.error) {
    return {
      ok: true,
      items: envelope.data,
      pagination: readPagination(envelope.meta),
    };
  }
  return {
    ok: false,
    code: envelope.error?.code ?? "RequestFailed",
    message: envelope.error?.message ?? "Không thể tải danh sách học phần.",
  };
}

export async function fetchRooms(params?: {
  page?: number;
  pageSize?: number;
}): Promise<ListResult<RoomSummary>> {
  const query = new URLSearchParams();
  query.set("page", String(params?.page ?? 1));
  query.set("pageSize", String(params?.pageSize ?? 100));

  const envelope = await apiRequest<RoomSummary[]>(`/rooms?${query.toString()}`);
  if (envelope.data && !envelope.error) {
    return {
      ok: true,
      items: envelope.data,
      pagination: readPagination(envelope.meta),
    };
  }
  return {
    ok: false,
    code: envelope.error?.code ?? "RequestFailed",
    message: envelope.error?.message ?? "Không thể tải danh sách phòng học.",
  };
}

export async function fetchClassSections(params: {
  page?: number;
  pageSize?: number;
  termId?: string;
  search?: string;
}): Promise<ListResult<ClassSectionSummary>> {
  const query = new URLSearchParams();
  query.set("page", String(params.page ?? 1));
  query.set("pageSize", String(params.pageSize ?? 25));
  if (params.termId) query.set("termId", params.termId);

  const envelope = await apiRequest<ClassSectionSummary[]>(`/class-sections?${query.toString()}`);
  if (envelope.data && !envelope.error) {
    let items = envelope.data;
    if (params.search?.trim()) {
      const needle = params.search.trim().toLowerCase();
      items = items.filter((section) => section.sectionCode.toLowerCase().includes(needle));
    }
    return {
      ok: true,
      items,
      pagination: readPagination(envelope.meta),
    };
  }
  return {
    ok: false,
    code: envelope.error?.code ?? "RequestFailed",
    message: envelope.error?.message ?? "Không thể tải danh sách lớp học phần.",
  };
}

export async function createClassSection(
  input: CreateClassSectionInput,
): Promise<ApiResult<CreateClassSectionData>> {
  const envelope = await apiRequest<CreateClassSectionData>("/class-sections", {
    method: "POST",
    body: input,
    idempotencyKey: newIdempotencyKey(),
  });
  if (envelope.data && !envelope.error) {
    return { ok: true, data: envelope.data };
  }
  return {
    ok: false,
    code: envelope.error?.code ?? "CreateFailed",
    message: envelope.error?.message ?? "Không thể tạo lớp học phần.",
  };
}

export async function importEnrollments(
  classSectionId: string,
  rows: { studentCode: string }[],
): Promise<ApiResult<EnrollmentImportData>> {
  const envelope = await apiRequest<EnrollmentImportData>("/enrollments/import", {
    method: "POST",
    body: { classSectionId, rows },
    idempotencyKey: newIdempotencyKey(),
  });
  if (envelope.data && !envelope.error) {
    return { ok: true, data: envelope.data };
  }
  return {
    ok: false,
    code: envelope.error?.code ?? "ImportFailed",
    message: envelope.error?.message ?? "Không thể nhập danh sách đăng ký.",
  };
}

/** Parse CSV text into enrollment import rows (studentCode column). */
export function parseEnrollmentCsv(text: string): { studentCode: string }[] {
  const lines = text.trim().split(/\r?\n/).filter((line) => line.trim().length > 0);
  if (lines.length === 0) return [];

  const headerLine = lines[0];
  if (!headerLine) return [];

  const headerCells = headerLine.split(",").map((cell) => cell.trim().toLowerCase());
  const codeIndex = headerCells.findIndex(
    (cell) => cell === "studentcode" || cell === "student_code" || cell === "ma_sinh_vien",
  );

  const dataLines = codeIndex >= 0 ? lines.slice(1) : lines;
  const valueIndex = codeIndex >= 0 ? codeIndex : 0;

  return dataLines
    .map((line) => {
      const cells = line.split(",").map((cell) => cell.trim());
      return { studentCode: cells[valueIndex] ?? "" };
    })
    .filter((row) => row.studentCode.length > 0);
}

export function formatTermDates(startDate: string, endDate: string): string {
  const start = new Date(`${startDate}T00:00:00`);
  const end = new Date(`${endDate}T00:00:00`);
  const fmt = new Intl.DateTimeFormat("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" });
  return `${fmt.format(start)} – ${fmt.format(end)}`;
}
