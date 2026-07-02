import type { ReactNode } from "react";
import styles from "./FeedbackAlert.module.css";

export type FeedbackAlertVariant = "brand" | "success" | "danger" | "warning" | "info";

export interface FeedbackAlertProps {
  title?: string;
  children: ReactNode;
  variant?: FeedbackAlertVariant;
  action?: ReactNode;
  className?: string;
}

export function FeedbackAlert({
  title,
  children,
  variant = "brand",
  action,
  className,
}: FeedbackAlertProps) {
  const classes = [styles.alert, styles[`variant-${variant}`], className ?? ""]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classes} role="alert">
      {title ? <p className={styles.title}>{title}</p> : null}
      <div className={styles.body}>{children}</div>
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  );
}
