export type AlertType = "AbsenceThreshold";

export type NotificationRecipientRole = "Student" | "Lecturer" | "AcademicAdmin";

export interface AbsenceRateSnapshot {
  unexcusedAbsenceRate: number;
  absenceThresholdPercent: number;
  excusedCountsTowardThreshold: boolean;
  eligibleSessionCount: number;
  unexcusedAbsentCount: number;
}

export interface PolicyAlertEvent {
  id: string;
  classSectionId: string;
  studentUserId: string;
  alertType: AlertType;
  unexcusedAbsenceRate: number;
  absenceThresholdPercent: number;
  sectionCode: string;
  payload: Record<string, unknown>;
  createdAt: string;
}

export interface NotificationQueueRow {
  id: string;
  alertEventId: string;
  recipientUserId: string;
  recipientRole: NotificationRecipientRole;
  channel: string;
  payload: Record<string, unknown>;
  status: string;
  createdAt: string;
}

export interface AbsenceThresholdAlertRow {
  alertEventId: string;
  classSectionId: string;
  sectionCode: string;
  studentUserId: string;
  studentCode: string;
  displayName: string;
  unexcusedAbsenceRate: number;
  absenceThresholdPercent: number;
  createdAt: string;
}

export interface EvaluateAbsenceThresholdResult {
  alertEmitted: boolean;
  alertEventId?: string;
  snapshot: AbsenceRateSnapshot;
}
