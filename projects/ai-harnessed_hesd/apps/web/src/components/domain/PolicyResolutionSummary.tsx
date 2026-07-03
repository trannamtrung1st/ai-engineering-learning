import { useState } from "react";
import type { PolicyPreviewState } from "../../lib/policy/resolve-preview.js";
import {
  formatPolicyFieldValue,
  POLICY_FIELD_LABELS,
  POLICY_PRECEDENCE_CHAIN,
  POLICY_SCOPE_LABELS,
  scopeSourceBadgeLabel,
} from "../../lib/i18n/policy-fields.js";
import styles from "./PolicyResolutionSummary.module.css";

export interface PolicyResolutionSummaryProps {
  preview: PolicyPreviewState | null;
  loading?: boolean;
}

export function PolicyResolutionSummary({ preview, loading = false }: PolicyResolutionSummaryProps) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    presentWindowMinutes: true,
    lateWindowMinutes: true,
    gpsRequired: true,
    manualEditWindowHours: true,
  });

  if (loading) {
    return (
      <div className={styles.policyResolutionSummary} data-testid="policy-resolution-summary">
        <h3 className={styles.header}>DC-09 · Chính sách hiệu lực</h3>
        <p className={styles.empty}>Đang tải xem trước…</p>
      </div>
    );
  }

  if (!preview) {
    return (
      <div className={styles.policyResolutionSummary} data-testid="policy-resolution-summary">
        <h3 className={styles.header}>DC-09 · Chính sách hiệu lực</h3>
        <p className={styles.empty}>
          Chọn lớp học phần để xem trước chuỗi ưu tiên BR-20 trước khi lưu.
        </p>
      </div>
    );
  }

  function toggleField(key: string) {
    setExpanded((current) => ({ ...current, [key]: !current[key] }));
  }

  return (
    <div className={styles.policyResolutionSummary} data-testid="policy-resolution-summary">
      <h3 className={styles.header}>DC-09 · Chính sách hiệu lực</h3>
      <p className={styles.precedence}>Thứ tự ưu tiên BR-20:</p>
      <ul className={styles.chain} aria-label="Chuỗi ưu tiên chính sách">
        {POLICY_PRECEDENCE_CHAIN.map((scope) => (
          <li key={scope} className={styles.chainItem}>
            {POLICY_SCOPE_LABELS[scope]}
          </li>
        ))}
      </ul>

      <div className={styles.accordion}>
        {preview.fields.map((field) => {
          const label = POLICY_FIELD_LABELS[field.key] ?? field.key;
          const isOpen = expanded[field.key] ?? false;
          return (
            <div key={field.key} className={styles.accordionItem}>
              <button
                type="button"
                className={styles.accordionTrigger}
                aria-expanded={isOpen}
                onClick={() => toggleField(field.key)}
              >
                <span>{label}</span>
                <span className={styles.sourceBadge}>{scopeSourceBadgeLabel(field.source)}</span>
              </button>
              {isOpen ? (
                <div className={styles.accordionPanel}>
                  <div className={styles.valueRow}>
                    <span>Giá trị hiệu lực</span>
                    <span className={styles.effectiveValue}>
                      {formatPolicyFieldValue(field.key, field.value)}
                    </span>
                  </div>
                  <div className={styles.valueRow}>
                    <span>Nguồn cấp</span>
                    <span className={styles.sourceBadge}>{scopeSourceBadgeLabel(field.source)}</span>
                  </div>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
