# Initial Idea — HESD Workshop Digital Attendance System

Xây dựng một hệ thống điểm danh số hóa cho workshop **Harness Engineering for Software Development (HESD)**, phục vụ quy mô khoảng **100–150 sinh viên mỗi đợt**.

Hiện tại, việc điểm danh thủ công bằng gọi tên, ký giấy hoặc kiểm tra danh sách gây mất thời gian, dễ sai sót và khó ngăn tình trạng điểm danh hộ. Mục tiêu của hệ thống là giúp ban tổ chức và giảng viên check-in nhanh hơn, quản lý dữ liệu tham dự chính xác hơn và xuất báo cáo sau mỗi buổi dễ dàng hơn.

## Vai trò (MVP)

**Admin** và **giảng viên (instructor)** là hai vai trò riêng biệt:

- **Admin** — quản lý metadata qua các trang admin: cấp tài khoản sinh viên (thủ công hoặc import CSV hàng loạt), quản lý danh sách tham dự (thủ công hoặc import CSV), xem audit log và metadata hệ thống. Admin **không** vận hành buổi workshop trực tiếp.
- **Giảng viên** — vận hành buổi học và tương tác với sinh viên: tạo/cấu hình buổi workshop, kích hoạt phiên, hiển thị QR, theo dõi điểm danh realtime, chỉnh thủ công khi có ngoại lệ, xuất CSV sau buổi.
- **Sinh viên** — đăng nhập bằng tài khoản do admin cấp, quét QR trên mobile web để check-in. Không tự đăng ký tài khoản trong giai đoạn pilot.

## Luồng chính

1. Admin cấp tài khoản sinh viên và quản lý danh sách tham dự (thủ công hoặc CSV).
2. Giảng viên tạo và cấu hình buổi workshop (gắn danh sách, thiết lập geofence GPS).
3. Giảng viên kích hoạt buổi; hệ thống hiển thị **QR code động**, tự thay đổi mỗi 30 giây.
4. Sinh viên dùng điện thoại quét QR trên mobile web.
5. Sinh viên đăng nhập tài khoản (do admin cấp trước đó).
6. Hệ thống kiểm tra QR còn hạn, sinh viên thuộc danh sách tham dự, chưa điểm danh buổi này và vị trí GPS nằm trong geofence hợp lệ.
7. Nếu hợp lệ, hệ thống ghi nhận điểm danh.
8. Giảng viên theo dõi danh sách check-in realtime, chỉnh thủ công khi có ngoại lệ và xuất báo cáo CSV sau buổi học.

## QR token

QR token không phải là token dùng một lần cho toàn bộ lớp. Vì QR được chiếu chung, nhiều sinh viên phải có thể quét cùng một mã trong thời gian còn hiệu lực. Do đó, QR token nên được hiểu là **short-lived multi-use session token**: token ngắn hạn, dùng được trong 30 giây, gắn với một buổi workshop cụ thể. Quy tắc "một lần" chỉ áp dụng ở cấp sinh viên: **mỗi sinh viên chỉ được check-in thành công một lần trong mỗi buổi workshop**.

## Geofence GPS (MVP)

- Mỗi buổi workshop có **geofence hình tròn**: tọa độ trung tâm (lat/lng) + bán kính (mét).
- **Mặc định: 100 m** — phù hợp phòng học hoặc phòng workshop nhỏ.
- **Cấu hình được: 50–200 m** khi tạo buổi.
- Giảng viên đặt tâm geofence khi cấu hình buổi (ghim địa điểm hoặc vị trí hiện tại).

## Chống gian lận

Hệ thống không đặt mục tiêu chống gian lận tuyệt đối. Thay vào đó, hệ thống dùng nhiều lớp kiểm tra để giảm gian lận: đăng nhập bắt buộc (tài khoản do admin cấp), QR hết hạn nhanh, mỗi sinh viên một lượt check-in, kiểm tra GPS cơ bản, ghi log các attempt bất thường và cho phép giảng viên xử lý thủ công khi cần.

## Phạm vi pilot

Tập trung vào các tính năng cốt lõi:

- Cấp tài khoản sinh viên (thủ công + import CSV hàng loạt)
- Quản lý danh sách tham dự (thủ công + import CSV)
- Tạo/cấu hình buổi workshop (geofence, gắn danh sách)
- QR động, check-in qua mobile web, kiểm tra GPS
- Dashboard realtime, manual fallback, audit log cơ bản, export CSV

Ngoài phạm vi giai đoạn đầu: SSO trường, tích hợp giáo vụ, chính sách chuyên cần toàn trường, nhận diện khuôn mặt, native mobile app, **tự đăng ký tài khoản sinh viên**.
