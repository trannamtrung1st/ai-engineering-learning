import type { ReactNode } from "react";
import styles from "./ActionBar.module.css";

export interface ActionBarProps {
  children: ReactNode;
  className?: string;
}

export function ActionBar({ children, className }: ActionBarProps) {
  return (
    <div className={[styles.bar, className ?? ""].filter(Boolean).join(" ")}>{children}</div>
  );
}
