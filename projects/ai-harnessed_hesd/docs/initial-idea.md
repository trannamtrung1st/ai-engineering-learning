# Business Requirements Document

# Attendly — Smart Campus Attendance

## 1. Vision and Objectives

### Vision

**Attendly** là hệ thống điểm danh số hóa cho môi trường trường học, giúp giảng viên điểm danh nhanh trong từng buổi học, sinh viên check-in thuận tiện bằng điện thoại, và phòng đào tạo có dữ liệu chuyên cần chính xác để quản lý lớp, môn học, học kỳ và chính sách học vụ.

Hệ thống thay thế quy trình điểm danh thủ công như gọi tên, ký giấy hoặc nhập danh sách bằng tay. Attendly giảm rủi ro điểm danh hộ bằng cách kết hợp xác thực tài khoản, QR động, kiểm tra vị trí, kiểm tra danh sách lớp và audit log.

### Objectives

| Goal                                 | User / Business Value                                            | Metric                                         | Target    | Timeframe           |
| ------------------------------------ | ---------------------------------------------------------------- | ---------------------------------------------- | --------- | ------------------- |
| Tự động hóa điểm danh lớp học        | Giảm thời gian điểm danh thủ công cho giảng viên                 | Thời gian hoàn tất check-in phần lớn sinh viên | < 5 phút  | Mỗi buổi học        |
| Tăng độ chính xác dữ liệu chuyên cần | Phòng đào tạo có dữ liệu đáng tin cậy theo lớp/môn               | Tỷ lệ bản ghi điểm danh hợp lệ                 | ≥ 98%     | Theo học kỳ         |
| Giảm rủi ro điểm danh hộ             | Hạn chế chia sẻ QR, check-in từ xa hoặc check-in nhiều lần       | Tỷ lệ failed/suspicious attempt có log         | 100%      | Mỗi buổi học        |
| Hỗ trợ quản lý học vụ                | Theo dõi tỷ lệ vắng, đi trễ, vắng có phép                        | Thời gian xuất báo cáo chuyên cần              | < 10 phút | Theo lớp/môn/học kỳ |
| Hỗ trợ xử lý ngoại lệ                | Tránh ghi vắng oan khi sinh viên gặp lỗi thiết bị, mạng hoặc GPS | Tỷ lệ ca ngoại lệ có thể xử lý thủ công        | ≥ 95%     | Mỗi buổi học        |

## 2. Problem Statement

Các lớp học trong trường hiện vẫn phụ thuộc nhiều vào quy trình điểm danh thủ công hoặc bán thủ công. Quy trình này gây ra nhiều vấn đề:

* Giảng viên mất thời gian gọi tên, ký giấy hoặc nhập danh sách.
* Dữ liệu chuyên cần dễ sai do nhập tay, thiếu người, trùng người hoặc cập nhật muộn.
* Sinh viên có thể điểm danh hộ nếu không có cơ chế xác thực đủ tốt.
* Phòng đào tạo khó theo dõi tỷ lệ vắng/đi trễ theo lớp, môn, học kỳ.
* Việc xử lý khiếu nại sau buổi học thiếu dữ liệu đối soát và audit log rõ ràng.

## 3. Affected Users

| User Group               | Pain Point                                                                 | Expected Benefit                                                     |
| ------------------------ | -------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Sinh viên                | Mất thời gian chờ điểm danh, dễ bị ghi vắng oan nếu quy trình thủ công sai | Check-in nhanh bằng điện thoại, xem lịch sử chuyên cần cá nhân       |
| Giảng viên               | Mất 5–15 phút mỗi buổi để điểm danh và tổng hợp thủ công                   | Mở buổi học, chiếu QR, theo dõi realtime, chỉnh ngoại lệ             |
| Phòng Đào Tạo            | Khó quản lý dữ liệu chuyên cần toàn trường                                 | Theo dõi báo cáo theo lớp/môn/học kỳ, cấu hình chính sách chuyên cần |
| Phòng CNTT               | Cần vận hành, tích hợp và bảo mật hệ thống                                 | Có hệ thống tập trung, phân quyền, audit log, khả năng tích hợp      |
| Ban lãnh đạo khoa/trường | Cần dữ liệu chuyên cần phục vụ quản lý chất lượng đào tạo                  | Có dashboard/report tổng quan và dữ liệu đáng tin cậy                |

## 4. Scope

### In Scope

Attendly bao gồm:

* Quản lý năm học, học kỳ, môn học, lớp học phần.
* Quản lý danh sách sinh viên đăng ký lớp học phần.
* Quản lý lịch học và từng buổi học cụ thể.
* Giảng viên mở/đóng buổi điểm danh.
* Sinh QR động cho từng buổi học.
* Sinh viên điểm danh bằng mobile web.
* Xác thực tài khoản sinh viên.
* Kiểm tra sinh viên có thuộc lớp học phần hay không.
* Kiểm tra mỗi sinh viên chỉ được điểm danh thành công một lần cho mỗi buổi học.
* Kiểm tra vị trí GPS ở mức cơ bản nếu policy của lớp yêu cầu.
* Ghi nhận trạng thái Present, Late, Absent, Excused, Manual Present.
* Giảng viên chỉnh sửa điểm danh trong phạm vi quyền.
* Phòng đào tạo quản lý chính sách chuyên cần.
* Báo cáo chuyên cần theo sinh viên, lớp, môn, giảng viên, học kỳ.
* Export CSV/Excel hoặc API để tích hợp hệ thống học vụ.
* Audit log cho check-in, failed attempt, chỉnh sửa thủ công và export dữ liệu.

### Out of Scope — Giai đoạn đầu

Các tính năng sau không thuộc phạm vi giai đoạn đầu:

* Nhận diện khuôn mặt.
* Native mobile app.
* Thanh toán học phí.
* Quản lý lịch thi.
* Chấm điểm học tập.
* LMS đầy đủ.
* Chống GPS spoofing tuyệt đối.
* Detect mock location chắc chắn trên mọi thiết bị.
* Theo dõi vị trí sinh viên liên tục ngoài thời điểm điểm danh.

## 5. Core Domain Model

| Entity           | Description                                                     |
| ---------------- | --------------------------------------------------------------- |
| Student          | Sinh viên trong trường                                          |
| Lecturer         | Giảng viên phụ trách lớp học phần                               |
| AcademicAdmin    | Nhân sự phòng đào tạo hoặc khoa có quyền quản lý dữ liệu học vụ |
| Term             | Học kỳ hoặc kỳ đào tạo                                          |
| Course           | Môn học, ví dụ Software Engineering, Database, AI Engineering   |
| ClassSection     | Lớp học phần cụ thể của một môn trong một học kỳ                |
| Enrollment       | Quan hệ sinh viên đăng ký vào lớp học phần                      |
| Timetable        | Lịch học dự kiến của lớp học phần                               |
| ClassSession     | Một buổi học cụ thể                                             |
| Room             | Phòng học hoặc địa điểm học                                     |
| AttendancePolicy | Chính sách chuyên cần áp dụng cho lớp/môn/khoa                  |
| QRSessionToken   | Token QR ngắn hạn cho một buổi học                              |
| CheckInAttempt   | Mỗi lần sinh viên thử điểm danh                                 |
| AttendanceRecord | Kết quả điểm danh cuối cùng của sinh viên trong một buổi        |
| AuditLog         | Log thao tác quan trọng trong hệ thống                          |

## 6. QR Token Design

### Correct Model

QR code được giảng viên chiếu cho cả lớp nên QR token không được thiết kế như **one-time-use global token**.

QR token đúng phải là:

> **Short-lived multi-use session token**

Nghĩa là:

* Token gắn với một buổi học cụ thể.
* Token có thời hạn ngắn, ví dụ 30 giây.
* Nhiều sinh viên trong lớp có thể dùng cùng token trong thời gian còn hiệu lực.
* Token hết hạn thì sinh viên phải quét QR mới.
* Token chỉ là một lớp kiểm tra, không tự động ghi nhận điểm danh nếu thiếu login, GPS và eligibility check.

### One-Time Rule

“One-time” áp dụng cho sinh viên, không áp dụng cho QR chung.

Quy tắc đúng là:

> Mỗi sinh viên chỉ được có một bản ghi điểm danh thành công cho mỗi buổi học.

Ví dụ:

* Student A quét QR lúc 08:00:10 → hợp lệ.
* Student B quét cùng QR lúc 08:00:15 → hợp lệ.
* Student A quét lại lúc 08:00:20 → bị từ chối vì đã điểm danh buổi này.

Nếu cần tăng bảo mật, Attendly có thể bổ sung **per-student check-in challenge token** sau khi sinh viên đăng nhập. Token này là token riêng của từng sinh viên và có thể one-time-use.

## 7. Capabilities

| ID     | Capability                  | Priority | Description                                                       |
| ------ | --------------------------- | -------- | ----------------------------------------------------------------- |
| CAP-01 | Quản lý lớp học phần        | Must     | Tạo/quản lý lớp học phần theo môn, học kỳ, giảng viên             |
| CAP-02 | Quản lý danh sách sinh viên | Must     | Import hoặc đồng bộ danh sách sinh viên đăng ký lớp               |
| CAP-03 | Quản lý lịch học            | Must     | Xác định các buổi học theo thời khóa biểu                         |
| CAP-04 | Mở/đóng buổi điểm danh      | Must     | Giảng viên mở điểm danh cho một buổi học cụ thể                   |
| CAP-05 | QR động                     | Must     | QR token tự xoay theo TTL, mặc định 30 giây                       |
| CAP-06 | Mobile web check-in         | Must     | Sinh viên quét QR và check-in bằng trình duyệt điện thoại         |
| CAP-07 | Xác thực sinh viên          | Must     | Sinh viên phải đăng nhập trước khi điểm danh                      |
| CAP-08 | Kiểm tra enrollment         | Must     | Chỉ sinh viên thuộc lớp học phần mới được điểm danh               |
| CAP-09 | Kiểm tra trùng điểm danh    | Must     | Một sinh viên chỉ được điểm danh thành công một lần/buổi          |
| CAP-10 | GPS validation              | Should   | Kiểm tra vị trí thiết bị trong bán kính hợp lệ                    |
| CAP-11 | Manual fallback             | Must     | Giảng viên/admin có thể chỉnh điểm danh khi có ngoại lệ           |
| CAP-12 | Realtime dashboard          | Should   | Giảng viên xem danh sách đã điểm danh, chưa điểm danh, bị từ chối |
| CAP-13 | Attendance policy           | Should   | Phòng đào tạo cấu hình rule vắng, trễ, vắng có phép               |
| CAP-14 | Attendance report           | Should   | Báo cáo theo sinh viên, lớp, môn, học kỳ                          |
| CAP-15 | Export data                 | Should   | Export CSV/Excel hoặc API cho hệ thống học vụ                     |
| CAP-16 | Audit log                   | Must     | Ghi lại check-in, failed attempt, chỉnh sửa và export dữ liệu     |

## 8. Attendance Status

| Status           | Meaning                                                                    |
| ---------------- | -------------------------------------------------------------------------- |
| Present          | Sinh viên điểm danh hợp lệ trong khoảng thời gian đúng giờ                 |
| Late             | Sinh viên điểm danh sau ngưỡng đúng giờ nhưng vẫn trong thời gian cho phép |
| Absent           | Sinh viên không điểm danh và không có lý do hợp lệ                         |
| Excused          | Sinh viên vắng có phép, được giảng viên/admin xác nhận                     |
| Manual Present   | Sinh viên được giảng viên/admin ghi nhận thủ công                          |
| Rejected Attempt | Lần thử điểm danh bị từ chối                                               |
| Suspicious       | Lần thử điểm danh có dấu hiệu bất thường, cần review                       |

## 9. Business Rules

| Rule ID | Condition                                                             | Trigger                            | Outcome                                               | Exception                                                            |
| ------- | --------------------------------------------------------------------- | ---------------------------------- | ----------------------------------------------------- | -------------------------------------------------------------------- |
| BR-01   | Buổi học chưa được mở điểm danh                                       | Sinh viên quét QR                  | Từ chối check-in                                      | Không                                                                |
| BR-02   | Buổi học đã đóng điểm danh                                            | Sinh viên gửi check-in             | Từ chối check-in                                      | Giảng viên/admin có thể chỉnh thủ công                               |
| BR-03   | QR token hết hạn                                                      | Sinh viên gửi check-in             | Từ chối, yêu cầu quét QR mới                          | Không                                                                |
| BR-04   | QR token không thuộc buổi học hiện tại                                | Sinh viên gửi check-in             | Từ chối, ghi failed attempt                           | Không                                                                |
| BR-05   | Sinh viên chưa đăng nhập                                              | Sinh viên mở link check-in         | Chuyển đến trang đăng nhập                            | Không                                                                |
| BR-06   | Sinh viên không thuộc lớp học phần                                    | Sinh viên gửi check-in             | Từ chối, ghi failed attempt                           | Admin/giảng viên có quyền có thể cập nhật enrollment nếu dữ liệu sai |
| BR-07   | Sinh viên đã điểm danh thành công trong buổi này                      | Sinh viên gửi check-in lại         | Từ chối, hiển thị “Bạn đã điểm danh buổi học này rồi” | Không                                                                |
| BR-08   | Thiết bị không cấp quyền GPS                                          | Sinh viên gửi check-in             | Từ chối self check-in, hướng dẫn bật GPS              | Manual fallback                                                      |
| BR-09   | GPS ngoài bán kính hợp lệ                                             | Sinh viên gửi check-in             | Từ chối hoặc đánh dấu cần review                      | Giảng viên/admin xác minh và chỉnh thủ công                          |
| BR-10   | GPS accuracy quá thấp hoặc dữ liệu bất thường                         | Sinh viên gửi check-in             | Yêu cầu thử lại hoặc đánh dấu Suspicious              | Manual review                                                        |
| BR-11   | Sinh viên check-in trong khoảng đúng giờ                              | Sinh viên gửi check-in hợp lệ      | Ghi nhận Present                                      | Không                                                                |
| BR-12   | Sinh viên check-in sau ngưỡng đúng giờ nhưng trước khi đóng điểm danh | Sinh viên gửi check-in hợp lệ      | Ghi nhận Late                                         | Tùy policy lớp/môn/khoa                                              |
| BR-13   | Sinh viên không check-in sau khi buổi học đóng                        | Hệ thống chốt buổi                 | Ghi nhận Absent                                       | Có thể Excused hoặc Manual Present nếu được xác nhận                 |
| BR-14   | Giảng viên chỉnh điểm danh                                            | Giảng viên thao tác trên dashboard | Cập nhật trạng thái, ghi audit log                    | Chỉ trong phạm vi lớp mình phụ trách                                 |
| BR-15   | Giảng viên chỉnh sau thời hạn cho phép                                | Giảng viên thao tác                | Từ chối hoặc yêu cầu admin phê duyệt                  | Theo policy trường                                                   |
| BR-16   | Admin chỉnh điểm danh                                                 | Admin thao tác                     | Cập nhật trạng thái, ghi audit log                    | Theo quyền admin                                                     |
| BR-17   | Tỷ lệ vắng vượt ngưỡng policy                                         | Hệ thống cập nhật sau mỗi buổi     | Gửi cảnh báo cho sinh viên/giảng viên/phòng đào tạo   | Vắng có phép có thể không tính                                       |
| BR-18   | Người dùng export dữ liệu                                             | Click export                       | Chỉ export dữ liệu trong phạm vi quyền                | Admin có thể export toàn trường                                      |
| BR-19   | Người dùng không có quyền xem báo cáo                                 | Truy cập report                    | Từ chối truy cập                                      | Không                                                                |

## 10. Attendance Policy

Attendly cần cho phép cấu hình policy theo cấp phù hợp:

* Toàn trường.
* Theo khoa/ngành.
* Theo môn học.
* Theo lớp học phần.

Các cấu hình policy nên bao gồm:

| Policy                   | Description                                      |
| ------------------------ | ------------------------------------------------ |
| Check-in opening time    | Cho phép mở điểm danh trước/sau giờ học bao lâu  |
| Present window           | Khoảng thời gian được tính là đúng giờ           |
| Late window              | Khoảng thời gian được tính là đi trễ             |
| Auto-absent rule         | Khi nào hệ thống tự chốt Absent                  |
| Absence threshold        | Tỷ lệ vắng tối đa, ví dụ 20%                     |
| Excused absence handling | Vắng có phép có tính vào tỷ lệ vắng hay không    |
| Manual edit window       | Giảng viên được chỉnh trong bao lâu sau buổi học |
| Admin approval rule      | Khi nào cần admin duyệt chỉnh sửa                |
| GPS required             | Lớp/môn có bắt buộc GPS không                    |
| GPS radius               | Bán kính hợp lệ theo phòng học hoặc địa điểm     |

## 11. GPS Policy

### Default Radius

* Bán kính mặc định đề xuất: 100m từ tọa độ phòng học.
* Có thể cấu hình theo phòng học, tòa nhà hoặc loại lớp học.
* Nên test thực địa trước khi chốt ngưỡng chính thức.
* Không nên hard-code 50m ở một chỗ và 100m ở chỗ khác.

### Important Limitation

GPS trên mobile web chỉ nên được xem là cơ chế **giảm rủi ro gian lận**, không phải cơ chế chống gian lận tuyệt đối.

Attendly không nên cam kết phát hiện 100% GPS spoofing vì:

* Trình duyệt không expose đầy đủ thông tin mock location.
* Hành vi iOS và Android khác nhau.
* GPS có thể sai lệch trong tòa nhà, tầng cao, khu vực nhiều vật cản.
* Website thường không thể đọc WiFi BSSID vì giới hạn bảo mật và quyền riêng tư.
* Fake GPS tinh vi vẫn có thể vượt qua các kiểm tra cơ bản.

Do đó, wording đúng nên là:

> Attendly giảm rủi ro điểm danh từ xa bằng GPS validation, QR động, login, audit log và manual review.

Không nên ghi:

> Attendly chống GPS spoofing tuyệt đối.

## 12. Anti-Fraud Strategy

Attendly áp dụng nhiều lớp giảm gian lận:

| Layer                      | Purpose                              |
| -------------------------- | ------------------------------------ |
| Login bắt buộc             | Xác định tài khoản sinh viên         |
| QR token TTL ngắn          | Giảm khả năng chia sẻ mã cũ          |
| QR token gắn với buổi học  | Ngăn dùng token sai lớp/sai buổi     |
| Một sinh viên một check-in | Ngăn check-in trùng                  |
| Enrollment validation      | Ngăn sinh viên ngoài lớp điểm danh   |
| GPS validation             | Giảm khả năng check-in từ xa         |
| Attendance window          | Giới hạn thời gian điểm danh         |
| Suspicious attempt log     | Phát hiện hành vi bất thường         |
| Manual review              | Cho phép xử lý ngoại lệ              |
| Audit log                  | Truy vết chỉnh sửa và export dữ liệu |

### Not Guaranteed

Attendly không đảm bảo loại bỏ hoàn toàn:

* Sinh viên chia sẻ tài khoản.
* Người khác cầm điện thoại của sinh viên và điểm danh hộ.
* Thiết bị dùng fake GPS tinh vi.
* Sinh viên đứng gần lớp nhưng không thực sự tham gia học.
* Sinh viên chụp QR gửi cho bạn trong cùng tòa nhà/khuôn viên.

Nếu trường muốn chống gian lận mạnh hơn, có thể cân nhắc phase sau:

* SSO/MFA.
* Device binding.
* Random in-class verification.
* Check-in nhiều lần ngẫu nhiên trong buổi học.
* Native app để có thêm tín hiệu thiết bị.
* Face verification, nếu được pháp lý và privacy cho phép.

## 13. User Flows

### Student Check-in Flow

1. Sinh viên vào lớp.
2. Giảng viên mở điểm danh và chiếu QR.
3. Sinh viên quét QR bằng điện thoại.
4. Nếu chưa đăng nhập, sinh viên đăng nhập.
5. Hệ thống yêu cầu quyền GPS nếu lớp yêu cầu GPS.
6. Sinh viên cấp quyền GPS.
7. Client gửi request gồm:

   * QR token.
   * Student identity/session.
   * GPS latitude/longitude.
   * GPS accuracy.
   * Timestamp.
8. Server validate:

   * Buổi học đang mở.
   * QR token đúng buổi.
   * QR token còn hạn.
   * Sinh viên thuộc lớp học phần.
   * Sinh viên chưa điểm danh thành công.
   * Request nằm trong attendance window.
   * GPS hợp lệ nếu policy yêu cầu.
9. Hệ thống ghi nhận Present hoặc Late.
10. Sinh viên thấy màn hình check-in thành công.

### Lecturer Flow

1. Giảng viên xem danh sách lớp học phần của mình.
2. Chọn buổi học hôm nay.
3. Mở điểm danh.
4. Hệ thống hiển thị QR động.
5. Giảng viên theo dõi dashboard realtime.
6. Giảng viên xử lý ngoại lệ nếu sinh viên gặp lỗi thiết bị/mạng/GPS.
7. Giảng viên đóng điểm danh hoặc để hệ thống tự đóng theo policy.
8. Giảng viên xem báo cáo buổi học/lớp học phần.

### Academic Admin Flow

1. Phòng đào tạo cấu hình học kỳ, môn học, lớp học phần.
2. Import hoặc đồng bộ danh sách sinh viên.
3. Cấu hình chính sách chuyên cần.
4. Theo dõi báo cáo chuyên cần theo lớp/môn/khoa/học kỳ.
5. Xử lý khiếu nại hoặc chỉnh sửa ngoài quyền giảng viên.
6. Export dữ liệu phục vụ học vụ.

## 14. Roles and Permissions

| Role             | Permissions                                                                                                           |
| ---------------- | --------------------------------------------------------------------------------------------------------------------- |
| Student          | Check-in, xem lịch sử chuyên cần cá nhân                                                                              |
| Lecturer         | Mở/đóng điểm danh lớp mình phụ trách, xem dashboard, chỉnh điểm danh trong thời hạn cho phép, export dữ liệu lớp mình |
| Department Admin | Xem/chỉnh dữ liệu trong phạm vi khoa/ngành, xử lý ngoại lệ, xem báo cáo tổng hợp                                      |
| Academic Admin   | Quản trị dữ liệu học vụ, cấu hình policy, xem/export dữ liệu toàn trường                                              |
| IT Admin         | Quản trị kỹ thuật, vận hành hệ thống, xem log kỹ thuật, không chỉnh dữ liệu học vụ nếu không được phân quyền          |
| System Auditor   | Xem audit log, phục vụ kiểm tra và xử lý khiếu nại                                                                    |

## 15. Data Requirements

### Attendance Record

Mỗi bản ghi điểm danh cần có:

* Student ID.
* Class Section ID.
* Class Session ID.
* Attendance status.
* Check-in timestamp.
* Method: QR, Manual, Admin Correction.
* Result: Success, Rejected, Suspicious.
* Reason code nếu bị từ chối.
* Người chỉnh sửa nếu có manual update.
* Audit reference.

### Check-in Attempt

Mỗi attempt nên lưu:

* Student ID.
* Class Session ID.
* QR token ID/hash.
* Timestamp.
* Device/browser metadata ở mức tối thiểu.
* IP address nếu policy cho phép.
* GPS validation result.
* Distance range.
* Accuracy range.
* Rejection reason nếu có.

### GPS Data Minimization

Để giảm rủi ro dữ liệu cá nhân:

* Không tracking GPS liên tục.
* Chỉ lấy GPS tại thời điểm điểm danh.
* Không lưu raw GPS lâu dài nếu không cần.
* Có thể lưu kết quả đã xử lý như pass/fail, distance range, accuracy range.
* Failed/suspicious attempt có thể lưu thêm dữ liệu trong thời gian giới hạn để phục vụ review.
* Cần retention policy rõ ràng.

## 16. Privacy and Security Requirements

Attendly cần đáp ứng các nguyên tắc sau:

* Chỉ thu thập dữ liệu cần thiết cho điểm danh.
* Thông báo rõ lý do cần quyền GPS.
* Không dùng dữ liệu vị trí cho mục đích ngoài điểm danh.
* Dữ liệu truyền qua mạng phải dùng HTTPS/TLS.
* Dữ liệu nhạy cảm cần được phân quyền truy cập.
* Export dữ liệu phải được kiểm soát theo vai trò.
* Mọi chỉnh sửa attendance phải có audit log.
* Mọi export dữ liệu phải có audit log.
* Có chính sách lưu trữ và xóa dữ liệu.
* Có quy trình xử lý khiếu nại điểm danh.

## 17. Constraints and Assumptions

### Constraints

| ID   | Constraint                                       | Impact                                                          |
| ---- | ------------------------------------------------ | --------------------------------------------------------------- |
| C-01 | Hệ thống chạy trên web/mobile web                | Không dùng được một số API native như detect mock GPS chắc chắn |
| C-02 | Sinh viên cần smartphone có camera và GPS        | Cần manual fallback                                             |
| C-03 | Mạng tại trường có thể không ổn định             | Cần retry, dashboard rõ ràng, fallback thủ công                 |
| C-04 | Trường có thể chưa có SSO ổn định                | Cần phương án login riêng hoặc import account                   |
| C-05 | Dữ liệu chuyên cần và vị trí là dữ liệu nhạy cảm | Cần RBAC, audit log, retention policy                           |
| C-06 | Lớp học có thể diễn ra ở nhiều phòng/campus      | Cần room/location configuration rõ ràng                         |
| C-07 | Lịch học có thể thay đổi                         | Cần hỗ trợ tạo session thủ công hoặc cập nhật từ timetable      |

### Assumptions

| ID | Assumption | Validation |
|---|---|
| A-01 | Đa số sinh viên có smartphone phù hợp | Khảo sát hoặc pilot trước |
| A-02 | Trường cung cấp danh sách sinh viên/lớp/môn qua API, CSV hoặc Excel | Xác nhận với phòng đào tạo/CNTT |
| A-03 | Giảng viên chấp nhận thao tác mở QR đầu buổi | Training và pilot |
| A-04 | GPS radius có thể cấu hình theo phòng/khu vực | Test thực địa |
| A-05 | Manual fallback là cần thiết để tránh vắng oan | Xác nhận với phòng đào tạo |
| A-06 | Chính sách vắng/trễ/vắng có phép khác nhau giữa đơn vị đào tạo | Cần policy engine cấu hình được |

## 18. Risks and Mitigation

| Risk                                             | Likelihood | Impact    | Mitigation                                                          |
| ------------------------------------------------ | ---------- | --------- | ------------------------------------------------------------------- |
| Sinh viên không có smartphone/hết pin/mất mạng   | Medium     | High      | Manual fallback, hướng dẫn trước buổi học                           |
| Sinh viên từ chối GPS                            | Medium     | Medium    | UX hướng dẫn cấp quyền, policy rõ ràng, fallback                    |
| GPS sai lệch gây từ chối oan                     | Medium     | High      | Radius phù hợp, retry, manual review                                |
| Fake GPS                                         | High       | High      | Không overclaim; dùng GPS + QR + login + log + review               |
| Chia sẻ QR trong 30 giây                         | High       | Medium    | QR TTL ngắn, login, enrollment check, GPS, one-check-in-per-student |
| Chia sẻ tài khoản                                | Medium     | High      | SSO/MFA nếu có, cảnh báo đăng nhập lạ, audit                        |
| Nhiều lớp điểm danh cùng lúc gây tải cao         | High       | High      | Load test, autoscaling, queue/retry, monitoring                     |
| Dữ liệu cá nhân bị lộ                            | Medium     | Very High | TLS, RBAC, data minimization, audit log, retention                  |
| Giảng viên thao tác sai                          | Medium     | Medium    | UX đơn giản, training, confirmation, audit                          |
| Dữ liệu lớp/môn từ hệ thống học vụ không đồng bộ | Medium     | High      | Import validation, sync log, fallback CSV                           |

## 19. Success Metrics

| Metric                                  | Target                         |
| --------------------------------------- | ------------------------------ |
| Median check-in time per student        | < 30 giây                      |
| 95th percentile check-in time           | < 90 giây                      |
| Valid check-in processing success rate  | ≥ 99%                          |
| Manual fallback rate                    | < 5% mỗi buổi                  |
| Failed attempt has reason code          | 100%                           |
| Attendance report generation time       | < 10 phút                      |
| Attendance edit has audit log           | 100%                           |
| Export action has audit log             | 100%                           |
| System availability during school hours | Theo SLA được trường phê duyệt |

## 20. Acceptance Criteria

### Class Session and QR

* Given giảng viên phụ trách một lớp học phần, when mở điểm danh cho buổi học, then hệ thống tạo QR động cho đúng buổi học đó.
* Given QR token còn trong TTL, when nhiều sinh viên cùng lớp quét token đó, then hệ thống cho phép xử lý nhiều check-in hợp lệ.
* Given QR token hết hạn, when sinh viên submit check-in, then hệ thống từ chối và yêu cầu quét lại QR mới.
* Given QR token thuộc buổi học khác, when sinh viên submit check-in, then hệ thống từ chối và ghi failed attempt.

### Student Check-in

* Given sinh viên đã đăng nhập và thuộc lớp học phần, when check-in hợp lệ, then hệ thống ghi nhận Present hoặc Late theo policy.
* Given sinh viên không thuộc lớp học phần, when check-in, then hệ thống từ chối.
* Given sinh viên đã điểm danh thành công, when check-in lại cùng buổi, then hệ thống từ chối.
* Given sinh viên không cấp GPS khi lớp yêu cầu GPS, when check-in, then hệ thống từ chối self check-in và hướng dẫn xử lý.

### Manual Fallback

* Given sinh viên gặp lỗi thiết bị/mạng/GPS, when giảng viên xác minh trực tiếp, then giảng viên có thể ghi nhận thủ công.
* Given giảng viên chỉnh điểm danh, when lưu thay đổi, then hệ thống ghi audit log gồm người sửa, thời điểm sửa, giá trị cũ, giá trị mới và lý do.
* Given giảng viên chỉnh ngoài thời hạn cho phép, when lưu thay đổi, then hệ thống yêu cầu admin xử lý hoặc từ chối theo policy.

### Reporting

* Given người dùng là giảng viên, when xem báo cáo, then chỉ thấy dữ liệu lớp/môn mình phụ trách.
* Given người dùng là admin phòng đào tạo, when xem báo cáo, then có thể xem dữ liệu theo phạm vi được phân quyền.
* Given người dùng không có quyền, when truy cập báo cáo hoặc export, then hệ thống từ chối.
* Given người dùng export dữ liệu, when export thành công, then hệ thống ghi audit log.

## 21. Recommended Delivery Phases

### Phase 1 — Core Attendance MVP

* Quản lý lớp học phần.
* Import danh sách sinh viên.
* Tạo/mở/đóng buổi học.
* QR động TTL 30 giây.
* Student login.
* Check-in QR + enrollment validation.
* Một sinh viên một check-in.
* Dashboard realtime cơ bản.
* Manual fallback.
* Export CSV cơ bản.

### Phase 2 — School Policy and Reporting

* Attendance policy theo lớp/môn/khoa.
* Present/Late/Absent/Excused.
* Báo cáo theo sinh viên/lớp/môn/học kỳ.
* Cảnh báo vượt ngưỡng vắng.
* Audit log đầy đủ.
* Role-based access control chi tiết.

### Phase 3 — Integration and Hardening

* Tích hợp SSO.
* Tích hợp hệ thống học vụ.
* Đồng bộ thời khóa biểu.
* Load test nhiều lớp đồng thời.
* Monitoring/alerting.
* Data retention policy.
* Security review.

### Phase 4 — Advanced Anti-Fraud, Optional

Chỉ làm nếu trường thật sự cần mức chống gian lận cao hơn:

* MFA.
* Device binding.
* Random check-in trong buổi học.
* Native app.
* Face verification.
* Cross-signal fraud detection.
