import { useEffect, useState, type FormEvent } from "react";
import {
  createClassSection,
  fetchCourses,
  fetchRooms,
  fetchTerms,
  type CourseSummary,
  type RoomSummary,
  type TermSummary,
} from "../../lib/api/academic-api";
import {
  DEFAULT_LECTURER_LABEL,
  SEED_LECTURER_USER_ID,
} from "../../lib/api/seed-fixtures";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { FeedbackAlert } from "../ui/FeedbackAlert";
import formStyles from "./AcademicForm.module.css";

const DAY_OPTIONS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

export interface ClassSectionCreateFormProps {
  onSuccess?: (result: { sectionId: string; generatedSessionCount?: number }) => void;
  onCancel?: () => void;
}

export function ClassSectionCreateForm({ onSuccess, onCancel }: ClassSectionCreateFormProps) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [terms, setTerms] = useState<TermSummary[]>([]);
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [rooms, setRooms] = useState<RoomSummary[]>([]);
  const [loadingLookups, setLoadingLookups] = useState(true);

  useEffect(() => {
    void (async () => {
      const [termsResult, coursesResult, roomsResult] = await Promise.all([
        fetchTerms({ page: 1, pageSize: 100, activeOnly: true }),
        fetchCourses({ page: 1, pageSize: 100 }),
        fetchRooms({ page: 1, pageSize: 100 }),
      ]);
      if (termsResult.ok) setTerms(termsResult.items);
      if (coursesResult.ok) setCourses(coursesResult.items);
      if (roomsResult.ok) setRooms(roomsResult.items);
      setLoadingLookups(false);
    })();
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setSubmitting(true);

    const form = new FormData(event.currentTarget);
    const includeSchedule = form.get("includeSchedule") === "on";
    const durationMinutes = Number.parseInt(String(form.get("durationMinutes") ?? "120"), 10);

    const result = await createClassSection({
      sectionCode: String(form.get("sectionCode") ?? "").trim(),
      termId: String(form.get("termId") ?? ""),
      courseId: String(form.get("courseId") ?? ""),
      lecturerUserId: String(form.get("lecturerUserId") ?? ""),
      defaultRoomId: String(form.get("defaultRoomId") ?? "") || undefined,
      capacity: Number.parseInt(String(form.get("capacity") ?? ""), 10) || undefined,
      scheduleTemplate: includeSchedule
        ? {
            dayOfWeek: String(form.get("dayOfWeek") ?? "Monday"),
            startTime: String(form.get("startTime") ?? "08:00"),
            durationMinutes: Number.isFinite(durationMinutes) ? durationMinutes : 120,
          }
        : undefined,
    });

    setSubmitting(false);
    if (result.ok) {
      const sessionNote =
        result.data.generatedSessionCount != null
          ? ` Đã tạo ${result.data.generatedSessionCount} buổi học Scheduled.`
          : "";
      setSuccess(`Đã tạo lớp ${result.data.sectionCode}.${sessionNote}`);
      onSuccess?.({
        sectionId: result.data.id,
        generatedSessionCount: result.data.generatedSessionCount,
      });
      return;
    }
    setError(result.message);
  }

  return (
    <Card elevated data-testid="class-section-create-form">
      <form className={formStyles.form} onSubmit={handleSubmit}>
        <h3 className={formStyles.label}>FRM-04 · Tạo lớp học phần</h3>

        {error ? (
          <FeedbackAlert variant="danger" title="Không thể tạo lớp học phần">
            {error}
          </FeedbackAlert>
        ) : null}

        {success ? (
          <FeedbackAlert variant="success" title="Tạo lớp học phần thành công">
            {success}
          </FeedbackAlert>
        ) : null}

        <label className={formStyles.field}>
          <span className={formStyles.label}>Mã lớp học phần</span>
          <input
            className={formStyles.input}
            name="sectionCode"
            required
            disabled={submitting || loadingLookups}
            placeholder="SE101-02"
          />
        </label>

        <div className={formStyles.gridTwo}>
          <label className={formStyles.field}>
            <span className={formStyles.label}>Học kỳ</span>
            <select className={formStyles.select} name="termId" required disabled={submitting || loadingLookups}>
              <option value="">Chọn học kỳ</option>
              {terms.map((term) => (
                <option key={term.id} value={term.id}>
                  {term.code} — {term.name}
                </option>
              ))}
            </select>
          </label>
          <label className={formStyles.field}>
            <span className={formStyles.label}>Học phần</span>
            <select className={formStyles.select} name="courseId" required disabled={submitting || loadingLookups}>
              <option value="">Chọn học phần</option>
              {courses.map((course) => (
                <option key={course.id} value={course.id}>
                  {course.code} — {course.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className={formStyles.gridTwo}>
          <label className={formStyles.field}>
            <span className={formStyles.label}>Giảng viên</span>
            <select
              className={formStyles.select}
              name="lecturerUserId"
              required
              disabled={submitting || loadingLookups}
              defaultValue={SEED_LECTURER_USER_ID}
            >
              <option value={SEED_LECTURER_USER_ID}>{DEFAULT_LECTURER_LABEL}</option>
            </select>
          </label>
          <label className={formStyles.field}>
            <span className={formStyles.label}>Phòng mặc định</span>
            <select className={formStyles.select} name="defaultRoomId" disabled={submitting || loadingLookups}>
              <option value="">Không chọn</option>
              {rooms.map((room) => (
                <option key={room.id} value={room.id}>
                  {room.code} — {room.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className={formStyles.field}>
          <span className={formStyles.label}>Sức chứa</span>
          <input
            className={formStyles.input}
            name="capacity"
            type="number"
            min={1}
            disabled={submitting || loadingLookups}
            placeholder="60"
          />
        </label>

        <fieldset className={formStyles.field}>
          <legend className={formStyles.label}>Lịch học mẫu (tạo buổi Scheduled)</legend>
          <label className={formStyles.checkboxRow}>
            <input name="includeSchedule" type="checkbox" defaultChecked disabled={submitting || loadingLookups} />
            <span>Tạo buổi học theo lịch mẫu</span>
          </label>
          <div className={formStyles.gridTwo}>
            <label className={formStyles.field}>
              <span className={formStyles.label}>Thứ</span>
              <select className={formStyles.select} name="dayOfWeek" defaultValue="Monday" disabled={submitting || loadingLookups}>
                {DAY_OPTIONS.map((day) => (
                  <option key={day} value={day}>
                    {day}
                  </option>
                ))}
              </select>
            </label>
            <label className={formStyles.field}>
              <span className={formStyles.label}>Giờ bắt đầu</span>
              <input
                className={formStyles.input}
                name="startTime"
                defaultValue="08:00"
                pattern="^\d{2}:\d{2}$"
                disabled={submitting || loadingLookups}
              />
            </label>
            <label className={formStyles.field}>
              <span className={formStyles.label}>Thời lượng (phút)</span>
              <input
                className={formStyles.input}
                name="durationMinutes"
                type="number"
                min={30}
                defaultValue={120}
                disabled={submitting || loadingLookups}
              />
            </label>
          </div>
        </fieldset>

        <div className={formStyles.actions}>
          <Button type="submit" disabled={submitting || loadingLookups}>
            {submitting ? "Đang lưu…" : "Tạo lớp học phần"}
          </Button>
          {onCancel ? (
            <Button type="button" variant="secondary" onClick={onCancel} disabled={submitting}>
              Hủy
            </Button>
          ) : null}
        </div>
      </form>
    </Card>
  );
}
