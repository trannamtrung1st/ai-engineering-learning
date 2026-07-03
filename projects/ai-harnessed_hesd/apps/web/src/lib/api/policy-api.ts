import type { ApiEnvelope } from "@attendly/domain";
import { apiRequest } from "./client.js";
import { createClassSection, fetchClassSections } from "./academic-api.js";
import type { PaginationMeta } from "./academic-api.js";
import {
  SEED_COURSE_ID,
  SEED_FACULTY_ID,
  SEED_FACULTY_LABEL,
  SEED_LECTURER_USER_ID,
  SEED_ROOM_ID,
  SEED_SECTION_ID,
  SEED_TERM_ID,
  DEFAULT_SECTION_LABEL,
  POLICY_LIST_FIXTURE_SECTION_CODE,
} from "./seed-fixtures.js";

export type PolicyScopeType = "Institution" | "Faculty" | "Course" | "ClassSection";

export interface PolicySummary {
  id: string;
  scopeType: PolicyScopeType;
  scopeId: string | null;
  checkInOpeningOffsetMinutes: number | null;
  presentWindowMinutes: number;
  lateWindowMinutes: number;
  autoCloseEnabled: boolean;
  absenceThresholdPercent: number | null;
  excusedCountsTowardThreshold: boolean;
  manualEditWindowHours: number;
  adminApprovalRequired: boolean;
  gpsRequired: boolean;
  gpsRadiusMeters: number | null;
  gpsMinAccuracyMeters: number | null;
  effectiveFrom: string | null;
  effectiveTo: string | null;
  isActive: boolean;
  createdAt: string;
}

export interface PolicyCreateInput {
  scopeType: PolicyScopeType;
  scopeId?: string | null;
  checkInOpeningOffsetMinutes?: number | null;
  presentWindowMinutes: number;
  lateWindowMinutes: number;
  autoCloseEnabled?: boolean;
  absenceThresholdPercent?: number | null;
  excusedCountsTowardThreshold?: boolean;
  manualEditWindowHours: number;
  adminApprovalRequired?: boolean;
  gpsRequired?: boolean;
  gpsRadiusMeters?: number | null;
  gpsMinAccuracyMeters?: number | null;
}

export type PolicyUpdateInput = Partial<PolicyCreateInput>;

export interface EffectivePolicyResponse {
  values: Record<string, unknown>;
  sources: Record<string, PolicyScopeType>;
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

export interface ScopeNameLookup {
  courses: Map<string, string>;
  sections: Map<string, string>;
  faculties: Map<string, string>;
}

export function buildDefaultScopeNameLookup(): ScopeNameLookup {
  return {
    faculties: new Map([[SEED_FACULTY_ID, SEED_FACULTY_LABEL]]),
    courses: new Map([[SEED_COURSE_ID, "SE101 · Nhập môn phần mềm"]]),
    sections: new Map([[SEED_SECTION_ID, DEFAULT_SECTION_LABEL]]),
  };
}

export function resolvePolicyScopeName(
  policy: Pick<PolicySummary, "scopeType" | "scopeId">,
  lookup: ScopeNameLookup,
): string {
  if (policy.scopeType === "Institution") {
    return "Toàn trường";
  }
  if (!policy.scopeId) {
    return policy.scopeType;
  }
  if (policy.scopeType === "Faculty") {
    return lookup.faculties.get(policy.scopeId) ?? policy.scopeId;
  }
  if (policy.scopeType === "Course") {
    return lookup.courses.get(policy.scopeId) ?? policy.scopeId;
  }
  return lookup.sections.get(policy.scopeId) ?? policy.scopeId;
}

export async function fetchPolicies(params: {
  page?: number;
  pageSize?: number;
  scopeLevel?: PolicyScopeType;
}): Promise<ListResult<PolicySummary>> {
  const query = new URLSearchParams();
  query.set("page", String(params.page ?? 1));
  query.set("pageSize", String(params.pageSize ?? 25));
  if (params.scopeLevel) {
    query.set("scopeLevel", params.scopeLevel);
  }

  const envelope = await apiRequest<PolicySummary[]>(`/policies?${query.toString()}`);
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
    message: envelope.error?.message ?? "Không thể tải danh sách chính sách.",
  };
}

export async function fetchPolicy(policyId: string): Promise<ApiResult<PolicySummary>> {
  const envelope = await apiRequest<PolicySummary>(`/policies/${policyId}`);
  if (envelope.data && !envelope.error) {
    return { ok: true, data: envelope.data };
  }
  return {
    ok: false,
    code: envelope.error?.code ?? "RequestFailed",
    message: envelope.error?.message ?? "Không thể tải chính sách.",
  };
}

export async function createPolicy(input: PolicyCreateInput): Promise<ApiResult<PolicySummary>> {
  const envelope = await apiRequest<PolicySummary>("/policies", {
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
    message: envelope.error?.message ?? "Không thể tạo chính sách.",
  };
}

export async function updatePolicy(
  policyId: string,
  input: PolicyUpdateInput,
): Promise<ApiResult<PolicySummary>> {
  const envelope = await apiRequest<PolicySummary>(`/policies/${policyId}`, {
    method: "PATCH",
    body: input,
    idempotencyKey: newIdempotencyKey(),
  });
  if (envelope.data && !envelope.error) {
    return { ok: true, data: envelope.data };
  }
  return {
    ok: false,
    code: envelope.error?.code ?? "UpdateFailed",
    message: envelope.error?.message ?? "Không thể cập nhật chính sách.",
  };
}

export async function fetchEffectivePolicy(
  classSectionId: string,
): Promise<ApiResult<EffectivePolicyResponse>> {
  const query = new URLSearchParams({ classSectionId });
  const envelope = await apiRequest<EffectivePolicyResponse>(
    `/policies/effective?${query.toString()}`,
  );
  if (envelope.data && !envelope.error) {
    return { ok: true, data: envelope.data };
  }
  return {
    ok: false,
    code: envelope.error?.code ?? "RequestFailed",
    message: envelope.error?.message ?? "Không thể tải chính sách hiệu lực.",
  };
}

const CLASS_SECTION_POLICY_FIXTURES: PolicyCreateInput[] = [
  {
    scopeType: "ClassSection",
    scopeId: SEED_SECTION_ID,
    presentWindowMinutes: 30,
    lateWindowMinutes: 15,
    manualEditWindowHours: 24,
    absenceThresholdPercent: 20,
    gpsRequired: true,
    gpsRadiusMeters: 100,
  },
  {
    scopeType: "ClassSection",
    presentWindowMinutes: 22,
    lateWindowMinutes: 12,
    manualEditWindowHours: 48,
    absenceThresholdPercent: 20,
    gpsRequired: false,
    gpsRadiusMeters: null,
  },
];

function isPolicyFixtureBootstrapEnabled(): boolean {
  return (
    import.meta.env.DEV ||
    (typeof window !== "undefined" &&
      (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"))
  );
}

/** Preview/dev bootstrap: PG-12 sort needs two ClassSection rows (TC-FR-24-014). */
export async function ensurePolicyListRegressionFixtures(): Promise<void> {
  if (!isPolicyFixtureBootstrapEnabled()) {
    return;
  }

  const list = await fetchPolicies({ page: 1, pageSize: 50, scopeLevel: "ClassSection" });
  if (!list.ok || list.pagination.totalItems >= 2) {
    return;
  }

  const sectionsResult = await fetchClassSections({ pageSize: 100 });
  if (!sectionsResult.ok) {
    return;
  }

  const sectionIds = sectionsResult.items.map((section) => section.id);
  if (
    !sectionsResult.items.some((section) => section.sectionCode === POLICY_LIST_FIXTURE_SECTION_CODE)
  ) {
    const created = await createClassSection({
      sectionCode: POLICY_LIST_FIXTURE_SECTION_CODE,
      termId: SEED_TERM_ID,
      courseId: SEED_COURSE_ID,
      lecturerUserId: SEED_LECTURER_USER_ID,
      defaultRoomId: SEED_ROOM_ID,
      capacity: 40,
    });
    if (created.ok) {
      sectionIds.push(created.data.id);
    }
  }

  const coveredScopeIds = new Set(list.items.map((policy) => policy.scopeId).filter(Boolean));
  for (const sectionId of sectionIds) {
    if (coveredScopeIds.size >= 2) {
      break;
    }
    if (coveredScopeIds.has(sectionId)) {
      continue;
    }
    const template =
      sectionId === SEED_SECTION_ID
        ? CLASS_SECTION_POLICY_FIXTURES[0]!
        : CLASS_SECTION_POLICY_FIXTURES[1]!;
    const createdPolicy = await createPolicy({ ...template, scopeId: sectionId });
    if (createdPolicy.ok) {
      coveredScopeIds.add(sectionId);
    }
  }
}
