import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { performVoluntaryLogout, VOLUNTARY_LOGOUT_PATH } from "../../lib/auth/logout";
import type { ButtonSize } from "../ui/Button";
import { Button } from "../ui/Button";
import styles from "./LogoutControl.module.css";

export interface LogoutControlProps {
  className?: string;
  size?: ButtonSize;
}

export function LogoutControl({ className, size = "sm" }: LogoutControlProps) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);

  async function handleLogout() {
    setBusy(true);
    try {
      await performVoluntaryLogout();
      navigate(VOLUNTARY_LOGOUT_PATH, { replace: true });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size={size}
      className={[styles.control, className ?? ""].filter(Boolean).join(" ")}
      onClick={() => void handleLogout()}
      disabled={busy}
      data-testid="logout-control"
    >
      {busy ? "Đang đăng xuất…" : "Đăng xuất"}
    </Button>
  );
}
