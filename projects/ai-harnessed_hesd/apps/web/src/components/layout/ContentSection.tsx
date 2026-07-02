import type { ReactNode } from "react";
import styles from "./ContentSection.module.css";

export interface ContentSectionProps {
  title?: string;
  titleClassName?: string;
  children: ReactNode;
  className?: string;
}

export function ContentSection({ title, titleClassName, children, className }: ContentSectionProps) {
  return (
    <section className={[styles.section, className ?? ""].filter(Boolean).join(" ")}>
      {title ? <h2 className={[styles.title, titleClassName ?? ""].filter(Boolean).join(" ")}>{title}</h2> : null}
      {children}
    </section>
  );
}
