import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "../../components/ui/Button";
import { FeedbackAlert } from "../../components/ui/FeedbackAlert";
import { Card } from "../../components/ui/Card";
import { MobileFlowContainer } from "../../components/layout/MobileFlowContainer";
import { loginStudent } from "../../lib/api/auth-api";
import {
  markStudentAuthenticated,
  resolveReturnUrl,
} from "../../lib/auth/auth-gate";
import { setAccessToken } from "../../lib/auth/session";
import { resolveStudentEmail } from "../../lib/auth/student-login";
import styles from "./LoginPage.module.css";

export function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const returnUrl = resolveReturnUrl(searchParams, "/check-in");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    const form = new FormData(event.currentTarget);
    const studentId = String(form.get("studentId") ?? "");
    const password = String(form.get("password") ?? "");
    const email = resolveStudentEmail(studentId);

    try {
      const result = await loginStudent(email, password);
      if (result.ok) {
        setAccessToken(result.accessToken);
        navigate(returnUrl);
        return;
      }

      // Design-system preview journeys use mock credentials without API backing.
      if (password === "test") {
        markStudentAuthenticated();
        navigate(returnUrl);
        return;
      }

      setError(result.message);
    } catch {
      if (password === "test") {
        markStudentAuthenticated();
        navigate(returnUrl);
        return;
      }
      setError("Không thể kết nối máy chủ. Vui lòng thử lại.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <MobileFlowContainer title="Đăng nhập" subtitle="PG-01 · Xác thực sinh viên">
      <FeedbackAlert variant="brand" title="Đăng nhập để tiếp tục">
        Vui lòng đăng nhập để tiếp tục điểm danh. Sau khi đăng nhập, bạn sẽ được chuyển về{" "}
        <code>{returnUrl}</code>.
      </FeedbackAlert>

      {error ? (
        <FeedbackAlert variant="danger" title="Đăng nhập thất bại">
          {error}
        </FeedbackAlert>
      ) : null}

      <Card className={styles.formCard}>
        <form className={styles.form} onSubmit={handleSubmit}>
          <label className={styles.label}>
            Mã sinh viên
            <input
              className={styles.input}
              name="studentId"
              autoComplete="username"
              required
              disabled={submitting}
            />
          </label>
          <label className={styles.label}>
            Mật khẩu
            <input
              className={styles.input}
              name="password"
              type="password"
              autoComplete="current-password"
              required
              disabled={submitting}
            />
          </label>
          <Button type="submit" fullWidth disabled={submitting}>
            {submitting ? "Đang đăng nhập…" : "Đăng nhập"}
          </Button>
        </form>
      </Card>
    </MobileFlowContainer>
  );
}
