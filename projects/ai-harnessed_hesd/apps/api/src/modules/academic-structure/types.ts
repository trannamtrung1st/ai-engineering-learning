export interface TermRow {
  id: string;
  code: string;
  name: string;
  startDate: string;
  endDate: string;
  isActive: boolean;
}

export interface CourseRow {
  id: string;
  code: string;
  name: string;
  facultyId: string;
  creditUnits: number | null;
  isActive: boolean;
}

export interface RoomRow {
  id: string;
  code: string;
  building: string | null;
  name: string;
  latitude: number | null;
  longitude: number | null;
  isActive: boolean;
}

export interface ClassSectionRow {
  id: string;
  sectionCode: string;
  termId: string;
  courseId: string;
  lecturerUserId: string;
  defaultRoomId: string | null;
  capacity: number | null;
  isActive: boolean;
}

export interface ScheduleTemplate {
  dayOfWeek: string;
  startTime: string;
  durationMinutes: number;
}

export interface PaginationMeta {
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
}

export interface ImportRejectedRow {
  rowNumber: number;
  code: string;
  message: string;
}

export interface EnrollmentImportResult {
  classSectionId: string;
  acceptedRows: number;
  rejectedRows: ImportRejectedRow[];
}
