/** Vietnamese roster UI copy — FR-03 / AC-03 / NFR-17 */
export const rosterCopy = {
  pageTitle: "Danh sách lớp",
  pageDescription: "Xem ghi danh theo lớp và môn học",
  importPageTitle: "Nhập danh sách lớp",
  importPageDescription: "Tải lên tệp CSV để ghi danh sinh viên",
  importButton: "Nhập CSV",
  filterClass: "Lớp",
  filterSubject: "Môn học",
  filterApply: "Xem danh sách",
  filterPrompt: "Chọn lớp và môn học để xem danh sách ghi danh",
  colStudentId: "MSSV",
  colStudentName: "Họ tên",
  colEnrolledAt: "Ngày ghi danh",
  emptyTitle: "Chưa có sinh viên ghi danh",
  emptyDescription: "Nhập danh sách từ tệp CSV hoặc chọn lớp-môn khác.",
  loadError: "Không thể tải danh sách ghi danh",
  retry: "Thử lại",
  accessDenied: "Bạn không có quyền xem danh sách này",
  dropzoneHint: "Kéo thả tệp CSV hoặc nhấn để chọn",
  dropzoneMaxSize: "Tối đa 5 MB, định dạng .csv",
  selectedFile: "Đã chọn",
  previewButton: "Xem trước",
  importConfirmButton: "Nhập danh sách",
  templateDownload: "Tải mẫu CSV",
  previewTitle: "Xem trước (10 dòng đầu)",
  validating: "Đang kiểm tra tệp…",
  importing: "Đang nhập danh sách…",
  parsing: "Đang đọc tệp…",
  invalidFileTitle: "Tệp không đúng định dạng",
  invalidFileMessage:
    "Tệp CSV phải có các cột: mã sinh viên, họ tên, mã lớp, mã môn học.",
  invalidFileApi: "File CSV không hợp lệ hoặc quá lớn",
  validationSummary: (valid: number, errors: number) =>
    `${valid} dòng hợp lệ, ${errors} dòng lỗi`,
  importCompleteTitle: "Hoàn tất nhập",
  importCompleteSuccess: (accepted: number, rejected: number) =>
    rejected > 0
      ? `Đã nhập ${accepted} dòng; ${rejected} dòng lỗi`
      : `Đã nhập ${accepted} dòng thành công`,
  importSuccessToast: "Đã nhập danh sách thành công",
  errorListTitle: "Chi tiết lỗi theo dòng",
  errorListToggle: "Xem chi tiết lỗi",
  errorListHide: "Ẩn chi tiết lỗi",
  errorRowLabel: (row: number, message: string) => `Dòng ${row}: ${message}`,
  backToRosters: "Quay lại danh sách lớp",
  importAnother: "Nhập tệp khác",
  viewRosterLink: "Xem danh sách lớp",
} as const;

export const ROSTER_CSV_TEMPLATE =
  "institutional_id,display_name,class_code,subject_code\nSV2026100,Nguyễn Văn A,HESD-01,SWE-101\n";
