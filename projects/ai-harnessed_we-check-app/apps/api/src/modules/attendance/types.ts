import type { AttendanceStatus, SessionStatus } from "@wecheck/domain";

export interface AttendanceSummary {
  enrolled: number;
  pending: number;
  present: number;
  absent: number;
  excused: number;
  rejected: number;
}

export interface AttendanceRecordDto {
  id: string;
  sessionId: string;
  studentId: string;
  institutionalId: string;
  displayName: string;
  status: AttendanceStatus;
  checkedInAt: string | null;
}

export interface AttendanceRecordRow {
  id: string;
  sessionId: string;
  studentId: string;
  status: AttendanceStatus;
  checkedInAt: Date | null;
  version: number;
}

export interface SessionContextRow {
  id: string;
  instructorId: string;
  classId: string;
  subjectId: string;
  status: SessionStatus;
  closedAt: Date | null;
}

export interface StudentHistoryItemDto {
  sessionId: string;
  sessionDate: string;
  subject: {
    id: string;
    code: string;
    name: string;
  };
  status: AttendanceStatus;
  checkedInAt: string | null;
}

export interface ManualEditInput {
  status: AttendanceStatus;
  note?: string;
}

export interface StudentHistoryQuery {
  subjectId?: string;
  from?: string;
  to?: string;
  limit: number;
  cursor?: string;
}
