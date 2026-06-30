import { UserRole, type UserRole as UserRoleType } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import { exportNotAllowed, forbidden, notFound } from "../../errors/api-error.js";
import { ReferenceRepository } from "../roster-enrollment/reference-repository.js";
import { formatAttendanceCsv } from "./csv-formatter.js";
import {
  ExportAuditRepository,
  ExportSecurityAuditRepository,
  ReportRepository,
} from "./repositories.js";
import type { ReportFilter } from "./types.js";

export class ExportService {
  private readonly reports: ReportRepository;
  private readonly references: ReferenceRepository;
  private readonly exportAudit: ExportAuditRepository;
  private readonly securityAudit: ExportSecurityAuditRepository;

  constructor(db: DbPool) {
    this.reports = new ReportRepository(db);
    this.references = new ReferenceRepository(db);
    this.exportAudit = new ExportAuditRepository(db);
    this.securityAudit = new ExportSecurityAuditRepository(db);
  }

  async exportCsv(
    filters: ReportFilter,
    actorId: string,
    role: UserRoleType,
  ): Promise<{ csv: string; rowCount: number }> {
    if (role !== UserRole.TrainingOfficeAdmin) {
      await this.securityAudit.logExportDenied(actorId, filters);
      throw exportNotAllowed();
    }

    if (!filters.classCode || !filters.subjectCode) {
      throw forbidden();
    }

    const classRecord = await this.references.findClassByCode(filters.classCode);
    const subjectRecord = await this.references.findSubjectByCode(filters.subjectCode);
    if (!classRecord || !subjectRecord) {
      throw notFound();
    }

    const rows = await this.reports.listExportRows(
      filters,
      classRecord.id,
      subjectRecord.id,
    );
    const csv = formatAttendanceCsv(rows);

    await this.exportAudit.insertSuccess({
      adminId: actorId,
      filterSummary: {
        classCode: filters.classCode,
        subjectCode: filters.subjectCode,
        from: filters.from,
        to: filters.to,
      },
      rowCount: rows.length,
    });

    return { csv, rowCount: rows.length };
  }

  async estimateRowCount(
    filters: ReportFilter,
    actorId: string,
    role: UserRoleType,
  ): Promise<number> {
    if (role !== UserRole.TrainingOfficeAdmin) {
      await this.securityAudit.logExportDenied(actorId, filters);
      throw exportNotAllowed();
    }

    if (!filters.classCode || !filters.subjectCode) {
      throw forbidden();
    }

    const classRecord = await this.references.findClassByCode(filters.classCode);
    const subjectRecord = await this.references.findSubjectByCode(filters.subjectCode);
    if (!classRecord || !subjectRecord) {
      throw notFound();
    }

    return this.reports.countExportRows(filters, classRecord.id, subjectRecord.id);
  }
}
