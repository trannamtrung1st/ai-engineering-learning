import type { ReactNode } from "react";
import styles from "./AppShell.module.css";

export interface AppShellProps {
  sidebar: ReactNode;
  header: ReactNode;
  children: ReactNode;
  compact?: boolean;
}

export function AppShell({ sidebar, header, children, compact = false }: AppShellProps) {
  return (
    <div className={[styles.shell, compact ? styles.compact : ""].filter(Boolean).join(" ")}>
      <a className="skip-link" href="#main-content">
        Bỏ qua đến nội dung chính
      </a>
      <aside className={styles.sidebar} aria-label="Điều hướng chính">
        {sidebar}
      </aside>
      <div className={styles.mainColumn}>
        <header className={styles.header}>{header}</header>
        <main id="main-content" className={styles.main}>
          {children}
        </main>
      </div>
    </div>
  );
}
