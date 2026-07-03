import type { ReactNode } from "react";
import styles from "./MobileFlowContainer.module.css";

export interface MobileFlowContainerProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
}

export function MobileFlowContainer({ title, subtitle, children }: MobileFlowContainerProps) {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <p className="eyebrow">Attendly</p>
        <h1>{title}</h1>
        {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}
      </header>
      <main className={styles.main}>{children}</main>
    </div>
  );
}
