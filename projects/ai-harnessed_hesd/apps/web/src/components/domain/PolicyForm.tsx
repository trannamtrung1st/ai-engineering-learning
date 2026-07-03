import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  createPolicy,
  fetchEffectivePolicy,
  updatePolicy,
  type PolicyScopeType,
  type PolicySummary,
} from "../../lib/api/policy-api";
import { fetchClassSections, fetchCourses } from "../../lib/api/academic-api";
import { SEED_FACULTY_ID, SEED_FACULTY_LABEL } from "../../lib/api/seed-fixtures";
import { POLICY_FIELD_HELPERS, POLICY_SCOPE_LABELS } from "../../lib/i18n/policy-fields";
import {
  mergeDraftIntoEffectivePreview,
} from "../../lib/policy/resolve-preview";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { FeedbackAlert } from "../ui/FeedbackAlert";
import { PolicyResolutionSummary } from "./PolicyResolutionSummary";
import formStyles from "./AcademicForm.module.css";
import styles from "./PolicyForm.module.css";

export interface PolicyFormProps {
  mode: "create" | "edit";
  initialPolicy?: PolicySummary;
  onSuccess?: () => void;
  onCancel?: () => void;
}

const SCOPE_TYPES: PolicyScopeType[] = ["Institution", "Faculty", "Course", "ClassSection"];

const DEFAULT_VALUES = {
  presentWindowMinutes: 15,
  lateWindowMinutes: 15,
  manualEditWindowHours: 24,
  absenceThresholdPercent: 20,
  gpsRadiusMeters: 100,
};

function defaultScopeIdForType(
  type: PolicyScopeType,
  courseOptions: { id: string }[],
  sectionOptions: { id: string }[],
): string {
  switch (type) {
    case "Institution":
      return "";
    case "Faculty":
      return SEED_FACULTY_ID;
    case "Course":
      return courseOptions[0]?.id ?? "";
    case "ClassSection":
      return sectionOptions[0]?.id ?? "";
  }
}

function scopeIdMatchesType(
  type: PolicyScopeType,
  id: string,
  courseOptions: { id: string }[],
  sectionOptions: { id: string }[],
): boolean {
  switch (type) {
    case "Institution":
      return true;
    case "Faculty":
      return id === SEED_FACULTY_ID;
    case "Course":
      return courseOptions.some((option) => option.id === id);
    case "ClassSection":
      return sectionOptions.some((option) => option.id === id);
  }
}

export function PolicyForm({ mode, initialPolicy, onSuccess, onCancel }: PolicyFormProps) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [scopeType, setScopeType] = useState<PolicyScopeType>(
    initialPolicy?.scopeType ?? "ClassSection",
  );
  const [scopeId, setScopeId] = useState(initialPolicy?.scopeId ?? "");
  const [presentWindowMinutes, setPresentWindowMinutes] = useState(
    initialPolicy?.presentWindowMinutes ?? DEFAULT_VALUES.presentWindowMinutes,
  );
  const [lateWindowMinutes, setLateWindowMinutes] = useState(
    initialPolicy?.lateWindowMinutes ?? DEFAULT_VALUES.lateWindowMinutes,
  );
  const [manualEditWindowHours, setManualEditWindowHours] = useState(
    initialPolicy?.manualEditWindowHours ?? DEFAULT_VALUES.manualEditWindowHours,
  );
  const [absenceThresholdPercent, setAbsenceThresholdPercent] = useState(
    initialPolicy?.absenceThresholdPercent ?? DEFAULT_VALUES.absenceThresholdPercent,
  );
  const [gpsRequired, setGpsRequired] = useState(initialPolicy?.gpsRequired ?? false);
  const [gpsRadiusMeters, setGpsRadiusMeters] = useState(
    initialPolicy?.gpsRadiusMeters ?? DEFAULT_VALUES.gpsRadiusMeters,
  );
  const [excusedCountsTowardThreshold, setExcusedCountsTowardThreshold] = useState(
    initialPolicy?.excusedCountsTowardThreshold ?? false,
  );
  const [adminApprovalRequired, setAdminApprovalRequired] = useState(
    initialPolicy?.adminApprovalRequired ?? false,
  );
  const [autoCloseEnabled, setAutoCloseEnabled] = useState(initialPolicy?.autoCloseEnabled ?? true);

  const [courseOptions, setCourseOptions] = useState<{ id: string; label: string }[]>([]);
  const [sectionOptions, setSectionOptions] = useState<{ id: string; label: string }[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [effectiveBase, setEffectiveBase] = useState<{
    values: Record<string, unknown>;
    sources: Record<string, PolicyScopeType>;
  } | null>(null);

  useEffect(() => {
    void (async () => {
      const [coursesResult, sectionsResult] = await Promise.all([
        fetchCourses({ pageSize: 100 }),
        fetchClassSections({ pageSize: 100 }),
      ]);
      if (coursesResult.ok) {
        setCourseOptions(
          coursesResult.items.map((course) => ({
            id: course.id,
            label: `${course.code} · ${course.name}`,
          })),
        );
      }
      if (sectionsResult.ok) {
        setSectionOptions(
          sectionsResult.items.map((section) => ({
            id: section.id,
            label: section.sectionCode,
          })),
        );
      }
    })();
  }, []);

  useEffect(() => {
    if (mode === "edit") {
      return;
    }
    setScopeId((current) => {
      if (scopeType === "Institution") {
        return "";
      }
      if (current && scopeIdMatchesType(scopeType, current, courseOptions, sectionOptions)) {
        return current;
      }
      return defaultScopeIdForType(scopeType, courseOptions, sectionOptions);
    });
  }, [scopeType, courseOptions, sectionOptions, mode]);

  function handleScopeTypeChange(type: PolicyScopeType) {
    setScopeType(type);
    if (mode === "edit") {
      return;
    }
    if (type === "Institution") {
      setScopeId("");
      return;
    }
    setScopeId((current) =>
      current && scopeIdMatchesType(type, current, courseOptions, sectionOptions)
        ? current
        : defaultScopeIdForType(type, courseOptions, sectionOptions),
    );
  }

  const previewSectionId = scopeType === "ClassSection" ? scopeId : sectionOptions[0]?.id ?? "";

  useEffect(() => {
    if (!previewSectionId) {
      setEffectiveBase(null);
      return;
    }
    setPreviewLoading(true);
    void (async () => {
      const result = await fetchEffectivePolicy(previewSectionId);
      setPreviewLoading(false);
      if (result.ok) {
        setEffectiveBase(result.data);
      } else {
        setEffectiveBase(null);
      }
    })();
  }, [previewSectionId, success]);

  const draftFields = useMemo(
    () => ({
      presentWindowMinutes,
      lateWindowMinutes,
      manualEditWindowHours,
      gpsRequired,
      gpsRadiusMeters: gpsRequired ? gpsRadiusMeters : null,
    }),
    [presentWindowMinutes, lateWindowMinutes, manualEditWindowHours, gpsRequired, gpsRadiusMeters],
  );

  const preview = useMemo(() => {
    if (!effectiveBase || !previewSectionId) return null;
    return mergeDraftIntoEffectivePreview(effectiveBase, scopeType, draftFields);
  }, [effectiveBase, previewSectionId, scopeType, draftFields]);

  function validateClient(): string | null {
    if (scopeType !== "Institution" && !scopeId) {
      return "Vui lòng chọn phạm vi áp dụng.";
    }
    if (
      scopeType !== "Institution" &&
      !scopeIdMatchesType(scopeType, scopeId, courseOptions, sectionOptions)
    ) {
      return "Phạm vi áp dụng không khớp với cấp chính sách đã chọn.";
    }
    if (presentWindowMinutes <= 0 || lateWindowMinutes < 0) {
      return "Cửa sổ điểm danh phải hợp lệ.";
    }
    if (absenceThresholdPercent < 0 || absenceThresholdPercent > 100) {
      return "Ngưỡng vắng mặt phải từ 0 đến 100.";
    }
    if (gpsRequired && (!gpsRadiusMeters || gpsRadiusMeters <= 0)) {
      return "Bán kính GPS phải lớn hơn 0 khi bật GPS.";
    }
    return null;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);

    const validationError = validateClient();
    if (validationError) {
      setError(validationError);
      return;
    }

    setSubmitting(true);
    const payload = {
      scopeType,
      scopeId: scopeType === "Institution" ? null : scopeId,
      presentWindowMinutes,
      lateWindowMinutes,
      manualEditWindowHours,
      absenceThresholdPercent,
      excusedCountsTowardThreshold,
      adminApprovalRequired,
      autoCloseEnabled,
      gpsRequired,
      gpsRadiusMeters: gpsRequired ? gpsRadiusMeters : null,
    };

    const result =
      mode === "edit" && initialPolicy
        ? await updatePolicy(initialPolicy.id, payload)
        : await createPolicy(payload);

    setSubmitting(false);
    if (result.ok) {
      setSuccess(
        mode === "edit" ? "Đã cập nhật chính sách thành công." : "Đã tạo chính sách thành công.",
      );
      onSuccess?.();
      return;
    }
    setError(result.message);
  }

  return (
    <div className={styles.formLayout} data-testid="policy-form">
      <Card elevated>
        <form className={formStyles.form} onSubmit={handleSubmit}>
          <h3 className={formStyles.label}>FRM-07 · Cấu hình chính sách điểm danh</h3>

          {error ? (
            <FeedbackAlert variant="danger" title="Không thể lưu chính sách">
              {error}
            </FeedbackAlert>
          ) : null}

          {success ? (
            <FeedbackAlert variant="success" title="Lưu thành công">
              {success}
            </FeedbackAlert>
          ) : null}

          <fieldset className={formStyles.field} disabled={mode === "edit" || submitting}>
            <legend className={formStyles.label}>Phạm vi (scope level)</legend>
            <div className={styles.scopeRadios}>
              {SCOPE_TYPES.map((type) => (
                <label key={type} className={styles.radioRow}>
                  <input
                    type="radio"
                    name="scopeType"
                    value={type}
                    checked={scopeType === type}
                    onChange={() => handleScopeTypeChange(type)}
                  />
                  {POLICY_SCOPE_LABELS[type]}
                </label>
              ))}
            </div>
          </fieldset>

          {scopeType === "Faculty" ? (
            <label className={formStyles.field}>
              <span className={formStyles.label}>Khoa</span>
              <select
                className={formStyles.select}
                value={scopeId}
                onChange={(event) => setScopeId(event.target.value)}
                disabled={mode === "edit" || submitting}
              >
                <option value={SEED_FACULTY_ID}>{SEED_FACULTY_LABEL}</option>
              </select>
            </label>
          ) : null}

          {scopeType === "Course" ? (
            <label className={formStyles.field}>
              <span className={formStyles.label}>Học phần</span>
              <select
                className={formStyles.select}
                value={scopeId}
                onChange={(event) => setScopeId(event.target.value)}
                disabled={mode === "edit" || submitting}
                required
              >
                <option value="">Chọn học phần…</option>
                {courseOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          {scopeType === "ClassSection" ? (
            <label className={formStyles.field}>
              <span className={formStyles.label}>Lớp học phần</span>
              <select
                className={formStyles.select}
                value={scopeId}
                onChange={(event) => setScopeId(event.target.value)}
                disabled={mode === "edit" || submitting}
                required
              >
                <option value="">Chọn lớp học phần…</option>
                {sectionOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          <div className={formStyles.gridTwo}>
            <label className={formStyles.field}>
              <span className={formStyles.label}>Cửa sổ Có mặt (phút)</span>
              <input
                className={formStyles.input}
                type="number"
                min={1}
                value={presentWindowMinutes}
                onChange={(event) => setPresentWindowMinutes(Number(event.target.value))}
                disabled={submitting}
                required
                data-testid="present-window-input"
              />
              <p className={formStyles.helper}>{POLICY_FIELD_HELPERS.presentWindowMinutes}</p>
            </label>
            <label className={formStyles.field}>
              <span className={formStyles.label}>Cửa sổ Muộn (phút)</span>
              <input
                className={formStyles.input}
                type="number"
                min={0}
                value={lateWindowMinutes}
                onChange={(event) => setLateWindowMinutes(Number(event.target.value))}
                disabled={submitting}
                required
              />
              <p className={formStyles.helper}>{POLICY_FIELD_HELPERS.lateWindowMinutes}</p>
            </label>
          </div>

          <div className={formStyles.gridTwo}>
            <label className={formStyles.field}>
              <span className={formStyles.label}>Cửa sổ chỉnh sửa thủ công (giờ)</span>
              <input
                className={formStyles.input}
                type="number"
                min={0}
                value={manualEditWindowHours}
                onChange={(event) => setManualEditWindowHours(Number(event.target.value))}
                disabled={submitting}
                required
                data-testid="manual-edit-window-input"
              />
              <p className={formStyles.helper}>{POLICY_FIELD_HELPERS.manualEditWindowHours}</p>
            </label>
            <label className={formStyles.field}>
              <span className={formStyles.label}>Ngưỡng vắng mặt (%)</span>
              <input
                className={formStyles.input}
                type="number"
                min={0}
                max={100}
                value={absenceThresholdPercent ?? ""}
                onChange={(event) => setAbsenceThresholdPercent(Number(event.target.value))}
                disabled={submitting}
              />
              <p className={formStyles.helper}>{POLICY_FIELD_HELPERS.absenceThresholdPercent}</p>
            </label>
          </div>

          <label className={styles.toggleRow}>
            <span>
              <span className={formStyles.label}>Bắt buộc GPS</span>
              <p className={formStyles.helper}>{POLICY_FIELD_HELPERS.gpsRequired}</p>
            </span>
            <input
              type="checkbox"
              role="switch"
              aria-label="Bắt buộc GPS"
              aria-checked={gpsRequired}
              checked={gpsRequired}
              onChange={(event) => setGpsRequired(event.target.checked)}
              disabled={submitting}
            />
          </label>

          <label className={`${formStyles.field} ${gpsRequired ? "" : styles.disabledField}`}>
            <span className={formStyles.label}>Bán kính GPS (m)</span>
            <input
              className={formStyles.input}
              type="number"
              min={1}
              value={gpsRadiusMeters ?? ""}
              onChange={(event) => setGpsRadiusMeters(Number(event.target.value))}
              disabled={!gpsRequired || submitting}
              data-testid="gps-radius-input"
            />
            <p className={formStyles.helper}>{POLICY_FIELD_HELPERS.gpsRadiusMeters}</p>
          </label>

          <label className={formStyles.checkboxRow}>
            <input
              type="checkbox"
              checked={excusedCountsTowardThreshold}
              onChange={(event) => setExcusedCountsTowardThreshold(event.target.checked)}
              disabled={submitting}
            />
            <span className={formStyles.label}>Tính vắng có phép vào ngưỡng</span>
          </label>

          <label className={formStyles.checkboxRow}>
            <input
              type="checkbox"
              checked={adminApprovalRequired}
              onChange={(event) => setAdminApprovalRequired(event.target.checked)}
              disabled={submitting}
            />
            <span className={formStyles.label}>Yêu cầu duyệt quản trị khi chỉnh sửa</span>
          </label>

          <label className={formStyles.checkboxRow}>
            <input
              type="checkbox"
              checked={autoCloseEnabled}
              onChange={(event) => setAutoCloseEnabled(event.target.checked)}
              disabled={submitting}
            />
            <span className={formStyles.label}>Tự đóng buổi học sau cửa sổ Muộn</span>
          </label>

          <div className={formStyles.actions}>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Đang lưu…" : mode === "edit" ? "Cập nhật chính sách" : "Lưu chính sách"}
            </Button>
            {onCancel ? (
              <Button type="button" variant="secondary" onClick={onCancel} disabled={submitting}>
                Hủy
              </Button>
            ) : null}
          </div>
        </form>
      </Card>

      <Card elevated className={styles.previewCard}>
        <PolicyResolutionSummary preview={preview} loading={previewLoading} />
      </Card>
    </div>
  );
}
