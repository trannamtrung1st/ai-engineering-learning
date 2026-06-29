import { UserRole, type UserRole as UserRoleType } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import { notFound, reportAccessDenied } from "../../errors/api-error.js";
import { AssignmentRepository } from "../roster-enrollment/assignment-repository.js";
import { ReferenceRepository } from "../roster-enrollment/reference-repository.js";
import { ReportRepository } from "./repositories.js";
import type { ClassSubjectSummaryDto, ReportFilter, SessionReportDto } from "./types.js";

export class ReportService {
  private readonly reports: ReportRepository;
  private readonly references: ReferenceRepository;
  private readonly assignments: AssignmentRepository;

  constructor(db: DbPool) {
    this.reports = new ReportRepository(db);
    this.references = new ReferenceRepository(db);
    this.assignments = new AssignmentRepository(db);
  }

  private async assertReportScope(
    requesterId: string,
    role: UserRoleType,
    classId: string,
    subjectId: string,
  ): Promise<void> {
    if (role === UserRole.TrainingOfficeAdmin) {
      return;
    }
    if (role === UserRole.Instructor) {
      const assigned = await this.assignments.hasAssignment(
        requesterId,
        classId,
        subjectId,
      );
      if (!assigned) {
        throw reportAccessDenied();
      }
      return;
    }
    throw reportAccessDenied();
  }

  async getSessionRoster(
    sessionId: string,
    requesterId: string,
    role: UserRoleType,
  ): Promise<SessionReportDto> {
    const session = await this.reports.findSessionContext(sessionId);
    if (!session) {
      throw notFound();
    }

    await this.assertReportScope(
      requesterId,
      role,
      session.class_id,
      session.subject_id,
    );

    const report = await this.reports.getSessionReport(sessionId);
    if (!report) {
      throw notFound();
    }
    return report;
  }

  async getClassSubjectSummary(
    filters: ReportFilter,
    requesterId: string,
    role: UserRoleType,
  ): Promise<ClassSubjectSummaryDto> {
    if (role === UserRole.Student) {
      throw reportAccessDenied();
    }

    const hasClassSubject = Boolean(filters.classCode && filters.subjectCode);

    if (role === UserRole.Instructor && !hasClassSubject) {
      throw reportAccessDenied();
    }

    if (hasClassSubject) {
      const classRecord = await this.references.findClassByCode(filters.classCode!);
      const subjectRecord = await this.references.findSubjectByCode(filters.subjectCode!);
      if (!classRecord || !subjectRecord) {
        throw notFound();
      }

      await this.assertReportScope(
        requesterId,
        role,
        classRecord.id,
        subjectRecord.id,
      );

      return this.reports.getClassSubjectSummary(
        filters,
        classRecord.id,
        subjectRecord.id,
        classRecord.code,
        subjectRecord.code,
      );
    }

    if (role !== UserRole.TrainingOfficeAdmin) {
      throw reportAccessDenied();
    }

    return this.reports.getClassSubjectSummary(filters);
  }
}
