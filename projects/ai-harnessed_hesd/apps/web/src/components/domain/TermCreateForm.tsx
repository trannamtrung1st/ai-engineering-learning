import { useState, type FormEvent } from "react";
import { createTerm } from "../../lib/api/academic-api";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { FeedbackAlert } from "../ui/FeedbackAlert";
import formStyles from "./AcademicForm.module.css";

export interface TermCreateFormProps {
  onSuccess?: () => void;
  onCancel?: () => void;
}

export function TermCreateForm({ onSuccess, onCancel }: TermCreateFormProps) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setSubmitting(true);

    const formEl = event.currentTarget;
    const formData = new FormData(formEl);
    const startDate = String(formData.get("startDate") ?? "");
    const endDate = String(formData.get("endDate") ?? "");

    if (endDate < startDate) {
      setError("Ngày kết thúc phải sau ngày bắt đầu.");
      setSubmitting(false);
      return;
    }

    const result = await createTerm({
      code: String(formData.get("code") ?? "").trim(),
      name: String(formData.get("name") ?? "").trim(),
      startDate,
      endDate,
      isActive: formData.get("isActive") === "on",
    });

    setSubmitting(false);
    if (result.ok) {
      setSuccess(`Đã tạo học kỳ ${result.data.code} thành công.`);
      formEl.reset();
      onSuccess?.();
      return;
    }
    setError(result.message);
  }

  return (
    <Card elevated data-testid="term-create-form">
      <form className={formStyles.form} onSubmit={handleSubmit}>
        <h3 className={formStyles.label}>FRM-02 · Tạo học kỳ mới</h3>

        {error ? (
          <FeedbackAlert variant="danger" title="Không thể tạo học kỳ">
            {error}
          </FeedbackAlert>
        ) : null}

        {success ? (
          <FeedbackAlert variant="success" title="Tạo học kỳ thành công">
            {success}
          </FeedbackAlert>
        ) : null}

        <div className={formStyles.gridTwo}>
          <label className={formStyles.field}>
            <span className={formStyles.label}>Mã học kỳ</span>
            <input className={formStyles.input} name="code" required disabled={submitting} placeholder="2026-2" />
          </label>
          <label className={formStyles.field}>
            <span className={formStyles.label}>Tên học kỳ</span>
            <input
              className={formStyles.input}
              name="name"
              required
              disabled={submitting}
              placeholder="Học kỳ 2 năm 2026"
            />
          </label>
        </div>

        <div className={formStyles.gridTwo}>
          <label className={formStyles.field}>
            <span className={formStyles.label}>Ngày bắt đầu</span>
            <input className={formStyles.input} name="startDate" type="date" required disabled={submitting} />
          </label>
          <label className={formStyles.field}>
            <span className={formStyles.label}>Ngày kết thúc</span>
            <input className={formStyles.input} name="endDate" type="date" required disabled={submitting} />
          </label>
        </div>

        <label className={formStyles.checkboxRow}>
          <input name="isActive" type="checkbox" defaultChecked disabled={submitting} />
          <span className={formStyles.label}>Đang hoạt động</span>
        </label>

        <div className={formStyles.actions}>
          <Button type="submit" disabled={submitting}>
            {submitting ? "Đang lưu…" : "Tạo học kỳ"}
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
