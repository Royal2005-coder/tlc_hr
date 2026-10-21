# Kiến trúc `tlc_hr`

`tlc_hr` là app Frappe chạy trên Frappe HR v16 (HRMS), ERPNext v16 và `erpnextvn`. App không sửa các app gốc, không sử dụng portal riêng ngoài desk Frappe chuẩn, và tuân thủ Clean Architecture. Toàn bộ nghiệp vụ được chia thành 4 lớp rõ ràng:

```
[ Desk Frappe / REST API / bench tlc ]
                 ↓
           interface/             adapters (controller doctype, doc_events, REST, CLI)
                 ↓
          application/            use cases (<Phân hệ>Service) phụ thuộc port domain
                 ↓
            domain/               thuần Python: entity, value object, rules, DomainError, ports
                 ↑
        infrastructure/           cài đặt ports (Frappe…Repository); customizing engine
contracts/     Pydantic v2 strict DTOs (Command, Result, Bundle customizing)
customizing/   Cấu hình khai báo YAML (roles, custom fields, permissions, workflows, dashboards, records)
```

## Ma trận phụ thuộc và ranh giới lớp

| Lớp | Được phép import | Cấm import |
|---|---|---|
| `contracts` | thư viện chuẩn, `pydantic` | `frappe`, `erpnext`, `hrms`, `application`, `domain`, `infrastructure`, `interface`, `setup` |
| `domain` | thư viện chuẩn, `contracts` | `frappe`, `erpnext`, `hrms`, `application`, `infrastructure`, `interface`, `setup` |
| `application` | `domain`, `contracts` | `frappe`, `erpnext`, `hrms`, `infrastructure`, `interface`, `setup` |
| `infrastructure` | `domain`, `contracts`, `frappe`, `erpnext`, `hrms` | `interface`, `application` |
| `interface` | tất cả | — |

Ranh giới này được kiểm tra tĩnh bằng AST qua `tlc_hr/tests/unit/test_architecture.py`.

## Cấu hình khai báo và vận hành kiểu SAP (A0)

1. **Khớp kiểu khai báo (Kind↔Payload):** Mỗi tài liệu YAML chỉ được mang khoá payload ứng với trường `kind`. Khai báo sai trường sẽ bị từ chối ngay ở bước validate contract.
2. **Thứ tự nạp siêu dữ liệu:** `DocTypeApplier` xử lý các bản ghi `DocType` trong `records.yaml` trước theo thứ tự phụ thuộc child table, sau đó đến `CustomFieldApplier`, `PermissionApplier`, `WorkflowMasterApplier`, `WorkflowApplier` và các applier bản ghi thông thường.
3. **An toàn giao dịch `apply`:** Engine thực thi diff trước, chỉ ghi thay đổi cần thiết. Khi có lỗi bản ghi dữ liệu, engine tự động gọi `frappe.db.rollback()` trước khi ném lỗi, ngăn tình trạng ghi dở dang. *Lưu ý:* Các thao tác DDL của Frappe/MariaDB (thêm cột Custom Field, cập nhật bảng DocType) mang tính ngầm commit theo MariaDB; khi gặp sự cố schema, cần khôi phục qua bản sao lưu site.
4. **Xuất cấu hình (`export`):** Lệnh `bench tlc config export <kind> [name]` xuất lại trạng thái cấu hình hiện tại của site theo định dạng YAML chuẩn contract mà không để lộ dữ liệu bí mật hay thông tin cá nhân.
5. **Đóng gói chuẩn:** `pyproject.toml` khai báo phụ thuộc trực tiếp `pydantic>=2.12,<3`, `PyYAML>=6,<7`, yêu cầu runtime Python 3.14 (theo Frappe 16), và cấu hình `tool.flit.sdist` để đóng gói toàn bộ `tlc_hr/customizing/**/*.yaml`.

## Nghiệp vụ chấm công và tăng ca (A1)

1. **Giải trình công (Attendance Request):**
   - Không cho phép giải trình lý do quên chấm công cho các ngày trong tương lai.
   - Quản lý trực tiếp duyệt cấp 1; người duyệt không được tự duyệt đơn của chính mình.
   - Điều chỉnh sau chốt (`POST_LOCK`) khi tạo mới chỉ dành cho vai trò Nhân sự (`HR_ROLES`) hoặc các luồng tích hợp nội bộ đã được chứng thực (`post_lock_creation_authorized`).
2. **Khoá kỳ công (Six-DocType Lock):**
   - Khoá chặt 6 DocType: `Attendance`, `Employee Checkin`, `Leave Application`, `Attendance Request`, `TLC Overtime Request`, `Shift Assignment`.
   - Bảo vệ cả chiều sửa ngày (trước lưu và sau lưu), chặn đổi ngày từ kỳ đã khoá sang kỳ mở hoặc ngược lại.
   - Gán ca mở (`Shift Assignment` không có `end_date`) được bảo vệ toàn bộ thời gian sau ngày bắt đầu.
   - Ngoại lệ mở khoá có ngữ cảnh: cờ `frappe.flags.tlc_post_lock` mang cấu trúc phạm vi (`employee`, `start`, `end`), chỉ cho phép ghi đúng bản ghi `Attendance` của nhân viên trong khoảng ngày được giải trình duyệt.
3. **Phép năm chuyển tiếp:**
   - Ngày hết hạn phép năm chuyển tiếp được tính theo ngày lịch: cố định đến hết **ngày 30 tháng 3** của năm kế tiếp (kể cả năm nhuận), được bảo đảm tại adapter `Leave Ledger Entry`.
4. **Tăng ca (TLC Overtime Request & Overtime Slip):**
   - Kiểm tra giới hạn Điều 107 Bộ luật Lao động (trần ngày 4h/12h tuỳ loại ngày, trần tháng 40h, trần năm 200h).
   - Kiểm soát quyền người đề nghị: chỉ cấp quản lý trực tiếp hoặc cấp trên trong cây phân cấp mới được lập đề nghị tăng ca cho nhân viên.
   - Đơn đã gửi không được phép sửa đổi người, ngày, giờ hoặc lý do.
   - Phiếu chi trả giờ tăng ca (`Overtime Slip`) chỉ thanh toán tối đa bằng số giờ đã có đơn duyệt hợp lệ trong ngày; cấm trùng lặp dòng ngày trên cùng một phiếu.
5. **Ranh giới an toàn ngoại lệ:**
   - `domain_errors()` tại `interface/errors.py` bọc an toàn cả lỗi hợp đồng `pydantic.ValidationError`, chuẩn hoá vị trí trường và loại lỗi theo mã định danh, tuyệt đối không in nội dung dữ liệu nhạy cảm hay thông điệp lỗi tự do ra giao diện người dùng.
