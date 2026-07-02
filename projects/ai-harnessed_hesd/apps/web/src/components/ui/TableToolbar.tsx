import type { ReactNode } from "react";
import { Button } from "../ui/Button";
import styles from "./TableToolbar.module.css";

export interface FilterOption {
  value: string;
  label: string;
}

export interface TableToolbarProps {
  termId?: string;
  termOptions?: FilterOption[];
  classSectionId?: string;
  sectionOptions?: FilterOption[];
  status?: string;
  statusOptions?: FilterOption[];
  search?: string;
  searchPlaceholder?: string;
  onSearchChange?: (value: string) => void;
  sortOrder?: "asc" | "desc";
  onTermChange?: (value: string) => void;
  onSectionChange?: (value: string) => void;
  onStatusChange?: (value: string) => void;
  onSortToggle?: () => void;
  onClearFilters?: () => void;
  showExport?: boolean;
  onExport?: () => void;
  exportDisabled?: boolean;
  children?: ReactNode;
}

export function TableToolbar({
  termId,
  termOptions = [],
  classSectionId,
  sectionOptions = [],
  status,
  statusOptions = [],
  search,
  searchPlaceholder = "Tìm kiếm…",
  onSearchChange,
  sortOrder = "desc",
  onTermChange,
  onSectionChange,
  onStatusChange,
  onSortToggle,
  onClearFilters,
  showExport = false,
  onExport,
  exportDisabled = false,
  children,
}: TableToolbarProps) {
  const hasActiveFilters = Boolean(termId || classSectionId || status || search);

  return (
    <div className={styles.toolbar} data-testid="table-toolbar">
      <div className={styles.filters}>
        {onSearchChange ? (
          <label className={styles.field}>
            <span className={styles.label}>Tìm kiếm</span>
            <input
              className={styles.input}
              type="search"
              aria-label="Tìm kiếm danh sách"
              placeholder={searchPlaceholder}
              value={search ?? ""}
              onChange={(event) => onSearchChange(event.target.value)}
            />
          </label>
        ) : null}
        {termOptions.length > 0 ? (
          <label className={styles.field}>
            <span className={styles.label}>Học kỳ</span>
            <select
              className={styles.select}
              aria-label="Lọc theo học kỳ"
              value={termId ?? ""}
              onChange={(event) => onTermChange?.(event.target.value)}
            >
              <option value="">Tất cả học kỳ</option>
              {termOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        {sectionOptions.length > 0 ? (
          <label className={styles.field}>
            <span className={styles.label}>Lớp học phần</span>
            <select
              className={styles.select}
              aria-label="Lọc theo lớp học phần"
              value={classSectionId ?? ""}
              onChange={(event) => onSectionChange?.(event.target.value)}
            >
              <option value="">Tất cả lớp</option>
              {sectionOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        {statusOptions.length > 0 ? (
          <label className={styles.field}>
            <span className={styles.label}>Trạng thái</span>
            <select
              className={styles.select}
              aria-label="Lọc theo trạng thái điểm danh"
              value={status ?? ""}
              onChange={(event) => onStatusChange?.(event.target.value)}
            >
              <option value="">Tất cả trạng thái</option>
              {statusOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        <Button variant="secondary" size="sm" type="button" onClick={onSortToggle}>
          Ngày {sortOrder === "desc" ? "↓" : "↑"}
        </Button>

        {hasActiveFilters ? (
          <Button variant="ghost" size="sm" type="button" onClick={onClearFilters}>
            Xóa bộ lọc
          </Button>
        ) : null}
      </div>

      <div className={styles.actions}>
        {children}
        {showExport ? (
          <Button variant="secondary" size="sm" disabled={exportDisabled} onClick={onExport}>
            Xuất CSV
          </Button>
        ) : null}
      </div>
    </div>
  );
}
