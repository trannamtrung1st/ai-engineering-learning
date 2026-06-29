import {
  GPS_RADIUS_DEFAULT_METERS,
  GPS_RADIUS_MAX_METERS,
  GPS_RADIUS_MIN_METERS,
  SessionStatus,
  hasValidRoomGps,
} from "@wecheck/domain";
import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { GpsMapPicker } from "@/components/domain/session/gps-map-picker";
import { fetchClasses, fetchSubjects, type ClassItem, type SubjectItem } from "@/lib/reference-api";
import {
  createSession,
  openSession,
  updateSession,
  type CreateSessionPayload,
  type PatchSessionPayload,
  type SessionDto,
} from "@/lib/sessions-api";
import { PREVIEW_ROOM_GPS } from "@/lib/preview-fixtures";

export interface SessionFormValues {
  classId: string;
  subjectId: string;
  title: string;
  scheduledStart: string;
  roomName: string;
  roomLatitude: number | null;
  roomLongitude: number | null;
  gpsRadiusMeters: number;
}

function defaultScheduledStartLocal(): string {
  const d = new Date();
  d.setHours(d.getHours() + 1, 0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function localDatetimeToIso(local: string): string {
  return new Date(local).toISOString();
}

function isoToLocalDatetime(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const initialValues: SessionFormValues = {
  classId: "",
  subjectId: "",
  title: "",
  scheduledStart: defaultScheduledStartLocal(),
  roomName: "",
  roomLatitude: PREVIEW_ROOM_GPS.latitude,
  roomLongitude: PREVIEW_ROOM_GPS.longitude,
  gpsRadiusMeters: GPS_RADIUS_DEFAULT_METERS,
};

export interface SessionFormProps {
  mode?: "create" | "edit" | "view";
  session?: SessionDto;
  classCode?: string;
  subjectCode?: string;
  onSaved?: (session: SessionDto) => void;
  onOpened?: (session: SessionDto) => void;
}

/** FR-04 / BR-07 / AC-04 — create session with GPS map picker */
export function SessionForm({
  mode = "create",
  session,
  classCode,
  subjectCode,
  onSaved,
  onOpened,
}: SessionFormProps) {
  const readOnly =
    mode === "view" || Boolean(session && session.status !== SessionStatus.Draft);
  const [values, setValues] = useState<SessionFormValues>(() =>
    session
      ? {
          classId: session.classId,
          subjectId: session.subjectId,
          title: session.title,
          scheduledStart: isoToLocalDatetime(session.scheduledStart),
          roomName: session.roomName,
          roomLatitude: session.roomLatitude,
          roomLongitude: session.roomLongitude,
          gpsRadiusMeters: session.gpsRadiusMeters,
        }
      : initialValues,
  );
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [subjects, setSubjects] = useState<SubjectItem[]>([]);
  const [loadingRefs, setLoadingRefs] = useState(mode === "create");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!session) return;
    setValues({
      classId: session.classId,
      subjectId: session.subjectId,
      title: session.title,
      scheduledStart: isoToLocalDatetime(session.scheduledStart),
      roomName: session.roomName,
      roomLatitude: session.roomLatitude,
      roomLongitude: session.roomLongitude,
      gpsRadiusMeters: session.gpsRadiusMeters,
    });
  }, [session]);

  useEffect(() => {
    if (mode !== "create") return;
    let cancelled = false;
    void (async () => {
      try {
        const [classItems, subjectItems] = await Promise.all([
          fetchClasses(),
          fetchSubjects(),
        ]);
        if (cancelled) return;
        setClasses(classItems);
        setSubjects(subjectItems);
        if (classItems[0] && !values.classId) {
          setValues((v) => ({ ...v, classId: classItems[0]!.id }));
        }
        if (subjectItems[0] && !values.subjectId) {
          setValues((v) => ({ ...v, subjectId: subjectItems[0]!.id }));
        }
      } finally {
        if (!cancelled) setLoadingRefs(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load refs once on mount
  }, [mode]);

  const gpsValid = hasValidRoomGps({
    roomLatitude: values.roomLatitude,
    roomLongitude: values.roomLongitude,
  });

  function validate(): boolean {
    const errors: Record<string, string> = {};
    if (!values.classId) errors.classId = "Vui lòng chọn lớp";
    if (!values.subjectId) errors.subjectId = "Vui lòng chọn môn học";
    if (!values.title.trim() || values.title.trim().length < 3) {
      errors.title = "Tên buổi học phải từ 3 đến 120 ký tự";
    }
    if (!values.roomName.trim()) errors.roomName = "Tên phòng là bắt buộc";
    if (!values.scheduledStart) errors.scheduledStart = "Thời gian bắt đầu là bắt buộc";
    if (
      values.gpsRadiusMeters < GPS_RADIUS_MIN_METERS ||
      values.gpsRadiusMeters > GPS_RADIUS_MAX_METERS
    ) {
      errors.gpsRadiusMeters = `Bán kính phải từ ${GPS_RADIUS_MIN_METERS} đến ${GPS_RADIUS_MAX_METERS} mét`;
    }
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  }

  function buildCreatePayload(): CreateSessionPayload {
    return {
      classId: values.classId,
      subjectId: values.subjectId,
      title: values.title.trim(),
      roomName: values.roomName.trim(),
      roomLatitude: values.roomLatitude,
      roomLongitude: values.roomLongitude,
      gpsRadiusMeters: values.gpsRadiusMeters,
      scheduledStart: localDatetimeToIso(values.scheduledStart),
    };
  }

  function buildPatchPayload(): PatchSessionPayload {
    return {
      title: values.title.trim(),
      roomName: values.roomName.trim(),
      roomLatitude: values.roomLatitude,
      roomLongitude: values.roomLongitude,
      gpsRadiusMeters: values.gpsRadiusMeters,
      scheduledStart: localDatetimeToIso(values.scheduledStart),
    };
  }

  async function handleSaveDraft() {
    if (!validate()) return;
    setSubmitting(true);
    setFormError(null);
    const result = await createSession(buildCreatePayload());
    setSubmitting(false);
    if (!result.ok) {
      setFormError(result.error.message ?? "Không thể lưu buổi học");
      return;
    }
    onSaved?.(result.data);
  }

  async function handleSaveSettings() {
    if (!session || mode !== "edit") return;
    if (!validate()) return;
    setSubmitting(true);
    setFormError(null);
    const result = await updateSession(session.id, buildPatchPayload());
    setSubmitting(false);
    if (!result.ok) {
      setFormError(result.error.message ?? "Không thể lưu cài đặt");
      return;
    }
    onSaved?.(result.data);
  }

  async function handleSaveAndOpen() {
    if (!validate()) return;
    if (!gpsValid) {
      setFormError("Vui lòng cấu hình tọa độ phòng học trước khi mở buổi học");
      return;
    }
    setSubmitting(true);
    setFormError(null);
    const created = await createSession(buildCreatePayload());
    if (!created.ok) {
      setSubmitting(false);
      setFormError(created.error.message ?? "Không thể tạo buổi học");
      return;
    }
    const opened = await openSession(created.data.id);
    setSubmitting(false);
    if (!opened.ok) {
      setFormError(opened.error.message ?? "Không thể mở buổi học");
      onSaved?.(created.data);
      return;
    }
    onOpened?.(opened.data);
  }

  if (loadingRefs) {
    return <p className="text-body text-text-secondary">Đang tải danh sách lớp…</p>;
  }

  return (
    <form
      className="flex flex-col gap-6 lg:grid lg:grid-cols-2 lg:gap-8"
      data-testid="session-form"
      onSubmit={(e) => e.preventDefault()}
    >
      <div className="flex flex-col gap-4">
        {formError ? (
          <Alert variant="danger" title="Không thể lưu">
            {formError}
          </Alert>
        ) : null}

        {mode !== "create" && classCode && subjectCode ? (
          <div className="text-body text-text-secondary">
            {classCode} · {subjectCode}
          </div>
        ) : (
          <>
            <div>
              <Label htmlFor="session-class">Lớp</Label>
              <select
                id="session-class"
                className="mt-1 flex min-h-touch w-full rounded-md border border-border bg-surface-raised px-3 text-body"
                value={values.classId}
                disabled={Boolean(readOnly)}
                aria-invalid={Boolean(fieldErrors.classId)}
                onChange={(e) => setValues((v) => ({ ...v, classId: e.target.value }))}
              >
                <option value="">Chọn lớp</option>
                {classes.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.code} — {c.name}
                  </option>
                ))}
              </select>
              {fieldErrors.classId ? (
                <p className="mt-1 text-small text-danger-600">{fieldErrors.classId}</p>
              ) : null}
            </div>

            <div>
              <Label htmlFor="session-subject">Môn học</Label>
              <select
                id="session-subject"
                className="mt-1 flex min-h-touch w-full rounded-md border border-border bg-surface-raised px-3 text-body"
                value={values.subjectId}
                disabled={Boolean(readOnly)}
                aria-invalid={Boolean(fieldErrors.subjectId)}
                onChange={(e) => setValues((v) => ({ ...v, subjectId: e.target.value }))}
              >
                <option value="">Chọn môn học</option>
                {subjects.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.code} — {s.name}
                  </option>
                ))}
              </select>
              {fieldErrors.subjectId ? (
                <p className="mt-1 text-small text-danger-600">{fieldErrors.subjectId}</p>
              ) : null}
            </div>
          </>
        )}

        <div>
          <Label htmlFor="session-title">Tên buổi học</Label>
          <Input
            id="session-title"
            value={values.title}
            disabled={Boolean(readOnly)}
            aria-invalid={Boolean(fieldErrors.title)}
            onChange={(e) => setValues((v) => ({ ...v, title: e.target.value }))}
          />
          {fieldErrors.title ? (
            <p className="mt-1 text-small text-danger-600">{fieldErrors.title}</p>
          ) : null}
        </div>

        <div>
          <Label htmlFor="session-start">Thời gian bắt đầu</Label>
          <Input
            id="session-start"
            type="datetime-local"
            value={values.scheduledStart}
            disabled={Boolean(readOnly)}
            aria-invalid={Boolean(fieldErrors.scheduledStart)}
            onChange={(e) => setValues((v) => ({ ...v, scheduledStart: e.target.value }))}
          />
          {fieldErrors.scheduledStart ? (
            <p className="mt-1 text-small text-danger-600">{fieldErrors.scheduledStart}</p>
          ) : null}
        </div>

        <div>
          <Label htmlFor="session-room">Phòng học</Label>
          <Input
            id="session-room"
            value={values.roomName}
            disabled={Boolean(readOnly)}
            aria-invalid={Boolean(fieldErrors.roomName)}
            onChange={(e) => setValues((v) => ({ ...v, roomName: e.target.value }))}
          />
          {fieldErrors.roomName ? (
            <p className="mt-1 text-small text-danger-600">{fieldErrors.roomName}</p>
          ) : null}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="session-lat">Vĩ độ</Label>
            <Input
              id="session-lat"
              type="number"
              step="any"
              value={values.roomLatitude ?? ""}
              disabled={Boolean(readOnly)}
              onChange={(e) =>
                setValues((v) => ({
                  ...v,
                  roomLatitude: e.target.value === "" ? null : Number(e.target.value),
                }))
              }
            />
          </div>
          <div>
            <Label htmlFor="session-lng">Kinh độ</Label>
            <Input
              id="session-lng"
              type="number"
              step="any"
              value={values.roomLongitude ?? ""}
              disabled={Boolean(readOnly)}
              onChange={(e) =>
                setValues((v) => ({
                  ...v,
                  roomLongitude: e.target.value === "" ? null : Number(e.target.value),
                }))
              }
            />
          </div>
        </div>

        <div>
          <Label htmlFor="session-radius">Bán kính GPS (m)</Label>
          <Input
            id="session-radius"
            type="number"
            min={GPS_RADIUS_MIN_METERS}
            max={GPS_RADIUS_MAX_METERS}
            value={values.gpsRadiusMeters}
            disabled={Boolean(readOnly)}
            title="Sinh viên phải ở trong bán kính này so với tọa độ phòng để điểm danh"
            onChange={(e) =>
              setValues((v) => ({ ...v, gpsRadiusMeters: Number(e.target.value) }))
            }
          />
          <p className="mt-1 text-small text-text-secondary">
            Sinh viên phải ở trong bán kính này so với tọa độ phòng để điểm danh
          </p>
          {fieldErrors.gpsRadiusMeters ? (
            <p className="mt-1 text-small text-danger-600">{fieldErrors.gpsRadiusMeters}</p>
          ) : null}
        </div>

        {mode === "create" ? (
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="ghost"
              disabled={submitting}
              data-testid="session-save-draft"
              onClick={() => void handleSaveDraft()}
            >
              Lưu nháp
            </Button>
            <Button
              type="button"
              disabled={submitting || !gpsValid}
              data-testid="session-save-and-open"
              onClick={() => void handleSaveAndOpen()}
            >
              Mở buổi học
            </Button>
          </div>
        ) : null}

        {mode === "edit" ? (
          <Button
            type="button"
            disabled={submitting}
            data-testid="session-save-settings"
            onClick={() => void handleSaveSettings()}
          >
            Lưu
          </Button>
        ) : null}
      </div>

      <GpsMapPicker
        latitude={values.roomLatitude}
        longitude={values.roomLongitude}
        radiusMeters={values.gpsRadiusMeters}
        readOnly={Boolean(readOnly)}
        onChange={(lat, lng) =>
          setValues((v) => ({ ...v, roomLatitude: lat, roomLongitude: lng }))
        }
      />
    </form>
  );
}
