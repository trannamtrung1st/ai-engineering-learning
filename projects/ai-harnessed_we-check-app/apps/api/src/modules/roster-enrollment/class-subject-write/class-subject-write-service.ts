import type { DbPool } from "../../../infra/db.js";
import {
  duplicateClassCode,
  duplicateSubjectCode,
} from "../../../errors/api-error.js";
import { isUniqueViolation } from "../../identity-auth/user-repository.js";
import { ReferenceRepository } from "../reference-repository.js";
import type { ClassRecord, SubjectRecord } from "../types.js";

export class ClassSubjectWriteService {
  private readonly references: ReferenceRepository;

  constructor(db: DbPool) {
    this.references = new ReferenceRepository(db);
  }

  async createClass(code: string, name: string): Promise<ClassRecord> {
    try {
      return await this.references.createClass(code, name);
    } catch (error) {
      if (isUniqueViolation(error)) {
        throw duplicateClassCode();
      }
      throw error;
    }
  }

  async createSubject(code: string, name: string): Promise<SubjectRecord> {
    try {
      return await this.references.createSubject(code, name);
    } catch (error) {
      if (isUniqueViolation(error)) {
        throw duplicateSubjectCode();
      }
      throw error;
    }
  }
}
