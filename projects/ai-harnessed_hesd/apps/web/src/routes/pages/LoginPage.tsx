import type { FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "../../components/ui/Button";
import { FeedbackAlert } from "../../components/ui/FeedbackAlert";
import { Card } from "../../components/ui/Card";
import { MobileFlowContainer } from "../../components/layout/MobileFlowContainer";
import { markStudentAuthenticated, resolveReturnUrl } from "../../lib/auth/auth-gate";
import styles from "./LoginPage.module.css";

export function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const returnUrl = resolveReturnUrl(searchParams, "/check-in");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    markStudentAuthenticated();
    navigate(returnUrl);
  }

  return (
    <MobileFlowContainer title="Đăng nhập" subtitle="PG-01 · Xác thực sinh viên">
      <FeedbackAlert variant="brand" title="Đăng nhập để tiếp tục">
        Vui lòng đăng nhập để tiếp tục điểm danh. Sau khi đăng nhập, bạn sẽ được chuyển về{" "}
        <code>{returnUrl}</code>.
      </FeedbackAlert>

      <Card className={styles.formCard}>
        <form className={styles.form} onSubmit={handleSubmit}>
          <label className={styles.label}>
            Mã sinh viên
            <input className={styles.input} name="studentId" autoComplete="username" required />
          </label>
          <label className={styles.label}>
            Mật khẩu
            <input
              className={styles.input}
              name="password"
              type="password"
              autoComplete="current-password"
              required
            />
          </label>
          <Button type="submit" fullWidth>
            Đăng nhập
          </Button>
        </form>
      </Card>
    </MobileFlowContainer>
  );
}
