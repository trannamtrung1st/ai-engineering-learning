import type { ListingQueryState } from "../../lib/listing/query-state";
import type { FilterOption } from "../ui/TableToolbar";
import styles from "./ExportScopeSummary.module.css";

export interface ExportScopeSummaryProps {
  roles: string[];
  query: ListingQueryState;
  termOptions: FilterOption[];
  sectionOptions: FilterOption[];
  totalItems: number;
}

function optionLabel(options: FilterOption[], value?: string): string {
  if (!value) return "Tất cả trong phạm vi";
  return options.find((option) => option.value === value)?.label ?? value.slice(0, 8);
}

function roleScopeLabel(roles: string[]): string {
  if (roles.includes("Lecturer")) return "Giảng viên · chỉ các lớp được phân công";
  if (roles.includes("DepartmentAdmin")) return "Quản trị khoa · phạm vi khoa được cấp";
  if (roles.includes("AcademicAdmin")) return "Quản trị học vụ · phạm vi cơ sở";
  return "Phạm vi đọc được cấp";
}

/** Traceability: FR-27 BR-18 AC-15 */
export function ExportScopeSummary({
  roles,
  query,
  termOptions,
  sectionOptions,
  totalItems,
}: ExportScopeSummaryProps) {
  return (
    <section className={styles.summary} aria-labelledby="export-scope-title">
      <div>
        <p className={styles.kicker}>ExportScopeSummary · FR-27 · BR-18</p>
        <h2 id="export-scope-title" className={styles.title}>
          Xác nhận phạm vi xuất CSV
        </h2>
        <p className={styles.copy}>
          CSV được tạo từ backend sau khi áp dụng quyền và bộ lọc hiện tại. Không mở rộng dữ liệu
          ngoài phạm vi vai trò.
        </p>
      </div>

      <dl className={styles.grid}>
        <div>
          <dt>Vai trò</dt>
          <dd>{roleScopeLabel(roles)}</dd>
        </div>
        <div>
          <dt>Học kỳ</dt>
          <dd>{optionLabel(termOptions, query.termId)}</dd>
        </div>
        <div>
          <dt>Lớp học phần</dt>
          <dd>{optionLabel(sectionOptions, query.classSectionId)}</dd>
        </div>
        <div>
          <dt>Trạng thái</dt>
          <dd>{query.status ?? "Tất cả trạng thái"}</dd>
        </div>
        <div>
          <dt>Khoảng ngày</dt>
          <dd>
            {query.from || query.to
              ? `${query.from ?? "Bắt đầu"} → ${query.to ?? "Hiện tại"}`
              : "Không giới hạn"}
          </dd>
        </div>
        <div>
          <dt>Dòng trong trang hiện tại</dt>
          <dd>{totalItems} bản ghi trong phạm vi đã lọc</dd>
        </div>
      </dl>
    </section>
  );
}
