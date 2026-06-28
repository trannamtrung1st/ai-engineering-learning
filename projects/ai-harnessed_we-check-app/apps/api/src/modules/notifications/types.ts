import type { NotificationType } from "@wecheck/domain";

export interface AbsenceThresholdPayload {
  subjectCode: string;
  subjectName: string;
  absenceRate: number;
  threshold: number;
  sessionCount: number;
  unexcusedAbsenceCount: number;
  sourceSessionId: string;
  studentId?: string;
  studentDisplayName?: string;
}

export interface NotificationDto {
  id: string;
  type: NotificationType;
  payload: AbsenceThresholdPayload;
  readAt: string | null;
  createdAt: string;
}

export interface NotificationListQuery {
  limit?: number;
  cursor?: string;
}

export interface SetAbsenceThresholdInput {
  thresholdPercent: number;
}
