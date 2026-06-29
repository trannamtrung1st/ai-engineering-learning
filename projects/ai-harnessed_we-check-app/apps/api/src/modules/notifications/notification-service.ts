import { SessionStatus } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import { forbidden, invalidPagination, notFound } from "../../errors/api-error.js";
import {
  computeAbsenceRate,
  exceedsAbsenceThreshold,
} from "./absence-threshold.js";
import {
  NotificationRepository,
  PolicyRepository,
  buildNextCursor,
  toNotificationDto,
} from "./repositories.js";
import type { AbsenceThresholdPayload, NotificationListQuery } from "./types.js";
import { decodeNotificationCursor } from "./validation.js";

export class NotificationService {
  private readonly notifications: NotificationRepository;
  private readonly policy: PolicyRepository;

  constructor(db: DbPool) {
    this.notifications = new NotificationRepository(db);
    this.policy = new PolicyRepository(db);
  }

  async getAbsencePolicy(): Promise<{
    thresholdPercent: number;
    autoWarningEnabled: boolean;
  }> {
    const [thresholdPercent, autoWarningEnabled] = await Promise.all([
      this.policy.getAbsenceThresholdPercent(),
      this.policy.getAbsenceAutoWarningEnabled(),
    ]);
    return { thresholdPercent, autoWarningEnabled };
  }

  async getAbsenceThresholdPercent(): Promise<number> {
    return this.policy.getAbsenceThresholdPercent();
  }

  async setAbsencePolicy(
    thresholdPercent: number,
    autoWarningEnabled: boolean,
    adminId: string,
  ): Promise<{ thresholdPercent: number; autoWarningEnabled: boolean }> {
    const [threshold, autoWarning] = await Promise.all([
      this.policy.setAbsenceThresholdPercent(thresholdPercent, adminId),
      this.policy.setAbsenceAutoWarningEnabled(autoWarningEnabled, adminId),
    ]);
    return { thresholdPercent: threshold, autoWarningEnabled: autoWarning };
  }

  async setAbsenceThresholdPercent(
    thresholdPercent: number,
    adminId: string,
  ): Promise<{ thresholdPercent: number }> {
    const value = await this.policy.setAbsenceThresholdPercent(
      thresholdPercent,
      adminId,
    );
    return { thresholdPercent: value };
  }

  async listForUser(
    userId: string,
    query: NotificationListQuery,
  ): Promise<{
    items: ReturnType<typeof toNotificationDto>[];
    nextCursor: string | null;
    totalCount: number;
  }> {
    const limit = query.limit ?? 50;
    let cursor: { createdAt: string; id: string } | undefined;

    if (query.cursor) {
      const decoded = decodeNotificationCursor(query.cursor);
      if (!decoded) {
        throw invalidPagination();
      }
      cursor = decoded;
    }

    const [page, totalCount] = await Promise.all([
      this.notifications.listForUser(userId, limit, cursor),
      this.notifications.countForUser(userId),
    ]);

    return {
      items: page.items.map(toNotificationDto),
      nextCursor: buildNextCursor(page.items, page.hasMore),
      totalCount,
    };
  }

  async markRead(notificationId: string, userId: string): Promise<void> {
    const existing = await this.notifications.findById(notificationId);
    if (!existing) {
      throw notFound();
    }
    if (existing.user_id !== userId) {
      throw forbidden();
    }
    await this.notifications.markRead(notificationId, userId);
  }

  async evaluateAbsenceThresholds(sessionId: string): Promise<void> {
    const session = await this.notifications.findSessionContext(sessionId);
    if (!session || session.status !== SessionStatus.Closed) {
      return;
    }

    const autoWarningEnabled = await this.policy.getAbsenceAutoWarningEnabled();
    if (!autoWarningEnabled) {
      return;
    }

    const [subject, thresholdPercent, students] = await Promise.all([
      this.notifications.findSubject(session.subjectId),
      this.policy.getAbsenceThresholdPercent(),
      this.notifications.listStudentsInSession(sessionId),
    ]);

    if (!subject || students.length === 0) {
      return;
    }

    const threshold = thresholdPercent / 100;
    const instructors = await this.notifications.listAssignedInstructors(
      session.classId,
      session.subjectId,
    );

    for (const student of students) {
      const stats = await this.notifications.getStudentAbsenceStats(
        student.studentId,
        session.classId,
        session.subjectId,
      );
      const { absenceRate, unexcusedAbsenceCount, sessionCount } =
        computeAbsenceRate(stats);

      if (!exceedsAbsenceThreshold(absenceRate, thresholdPercent)) {
        continue;
      }

      const basePayload: Omit<
        AbsenceThresholdPayload,
        "studentId" | "studentDisplayName"
      > = {
        subjectCode: subject.code,
        subjectName: subject.name,
        absenceRate,
        threshold,
        sessionCount,
        unexcusedAbsenceCount,
        sourceSessionId: sessionId,
      };

      await this.notifications.createAbsenceWarning(student.studentId, {
        ...basePayload,
      });

      for (const instructorId of instructors) {
        await this.notifications.createAbsenceWarning(instructorId, {
          ...basePayload,
          studentId: student.studentId,
          studentDisplayName: student.displayName,
        });
      }
    }
  }
}

export { PolicyRepository } from "./repositories.js";
