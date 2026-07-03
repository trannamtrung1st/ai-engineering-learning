/**
 * Traceability: FR-29 FR-30 BR-22 AC-19 NFR-13
 */
import { describe, expect, it } from "vitest";
import {
  apiActionTypeToDbFilter,
  deriveApiActionType,
  parseAuditLogQuery,
} from "./validation.js";

describe("audit-and-compliance validation — FR-29 FR-30 BR-22", () => {
  it("parses paginated audit query with actionType manual_update", () => {
    const parsed = parseAuditLogQuery({
      actionType: "manual_update",
      targetType: "AttendanceRecord",
      page: "2",
      pageSize: "50",
    });
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.filters.page).toBe(2);
    expect(parsed.filters.pageSize).toBe(50);
    expect(parsed.filters.actionType).toBe("manual_update");
  });

  it("rejects unknown actionType filter", () => {
    const parsed = parseAuditLogQuery({ actionType: "unknown_action" });
    expect(parsed.ok).toBe(false);
  });

  it("maps API manual_update to AttendanceUpdate subtype filter", () => {
    const mapped = apiActionTypeToDbFilter("manual_update");
    expect(mapped.dbActionTypes).toEqual(["AttendanceUpdate"]);
    expect(mapped.attendanceSubtype).toBe("manual_update");
  });

  it("maps CheckInAttemptRecorded to CheckInAttempt db action", () => {
    const mapped = apiActionTypeToDbFilter("CheckInAttemptRecorded");
    expect(mapped.dbActionTypes).toEqual(["CheckInAttempt"]);
  });

  it("derives admin_override from attendance audit payload", () => {
    const apiType = deriveApiActionType({
      action_type: "AttendanceUpdate",
      actor_user_id: "actor-1",
      new_value: {
        status: "Excused",
        auditActionSubtype: "admin_override",
        actorRole: "AcademicAdmin",
      },
    });
    expect(apiType).toBe("admin_override");
  });

  it("derives status_finalization for system actor absent assignment", () => {
    const apiType = deriveApiActionType({
      action_type: "AttendanceUpdate",
      actor_user_id: null,
      new_value: {
        status: "Absent",
        auditActionSubtype: "status_finalization",
      },
    });
    expect(apiType).toBe("status_finalization");
  });

  it("derives CheckInAttemptRecorded from CheckInAttempt rows", () => {
    const apiType = deriveApiActionType({
      action_type: "CheckInAttempt",
      actor_user_id: "student-1",
      new_value: { outcome: "ExpiredQr" },
    });
    expect(apiType).toBe("CheckInAttemptRecorded");
  });
});
