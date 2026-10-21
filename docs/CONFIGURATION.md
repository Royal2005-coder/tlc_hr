# Cấu hình khai báo (Customizing Reference)

Toàn bộ cấu hình nghiệp vụ của TLC HRM được đặc tả dưới dạng declarative YAML đặt tại `tlc_hr/customizing/**/*.yaml`. Hệ thống đọc và đối soát cấu hình bằng schema Pydantic v2 strict trong `tlc_hr/contracts/customizing.py`.

## Mô hình ánh xạ SAP ↔ Frappe TLC

| Khái niệm SAP | Triển khai trong TLC HR (Frappe v16) | Ghi chú vận hành |
|---|---|---|
| **DDIC** (Data Dictionary) | `DocType` JSON trong `tlc_hr/doctype/` + `records.yaml` (DocType) + `custom_fields.yaml` | `DocTypeApplier` xử lý bảng con trước bảng cha; `CustomFieldApplier` cập nhật trường bổ sung. |
| **SPRO / IMG** (Customizing) | `tlc_hr/customizing/*.yaml` | Nguồn sự thật duy nhất, kiểm soát qua git. |
| **Transport STMS** | Git commit → image build → `bench migrate` (tự chạy `tlc config apply`) | Tự động, idempotent, chỉ ghi phần lệch. |
| **SE16** (Đối soát dữ liệu) | `bench --site <site> tlc config plan` | So khớp giữa database và YAML, trả exit code 2 khi có sai lệch. |
| **BAdI / User Exit** | `hooks.py` (`doc_events`, `override_doctype_class`, `permission_query_conditions`) | Gọi vào adapter mỏng tại `tlc_hr/interface/`. |
| **CLI / ABAP Report** | Lệnh click `bench tlc ...` (`tlc_hr/commands.py` và `tlc_hr/interface/cli.py`) | Hỗ trợ `validate`, `plan`, `apply`, `export`, `doctor`, `seed`. |
| **RFC / BAPI** | REST API chuẩn của Frappe (`/api/method/...`, `/api/resource/...`) | Gọi chung use case với giao diện người dùng. |

## Danh mục tài nguyên cấu hình (`kind`)

Mỗi file YAML khai báo bắt buộc phải có `version: 1`, `kind: <loại>`, trường `description`, và chỉ chứa payload tương ứng với loại đó:

1. `roles`: Danh sách vai trò người dùng (`name`, `desk_access`, `home_page`).
2. `custom_fields`: Trường mở rộng trên DocType chuẩn (`doctype`, danh sách `fields`).
3. `permissions`: Ma trận phân quyền vai trò (`doctype`, `role`, `permlevel`, `rights` gồm các ký tự `r w c d s x a`).
4. `workflow`: Quy trình phê duyệt trạng thái (`name`, `doctype`, `states`, `transitions`).
5. `email_templates`: Mẫu thông báo email gắn với cấu hình hệ thống (`name`, `subject`, `html`, `hr_setting`).
6. `dashboards`: Thẻ số liệu (`number_cards`) và biểu đồ (`charts`).
7. `workspaces`: Không gian làm việc cho từng vai trò (`workspaces`, `shortcuts`).
8. `records`: Bản ghi cấu hình hệ thống: ca làm việc (`Shift Type`), địa điểm (`Shift Location`), loại nghỉ (`Leave Type`), tham số luật lao động (`VN Payroll Settings`), v.v.
9. `accounts`: Cấu hình tài khoản lương TT200 (`account_types`, `company_defaults`).
10. `payroll`: Khai báo thành phần lương (`components`) và cấu trúc tính lương (`structure` bao gồm `earnings`, `deductions`, `employer_contributions`, `effective_from`).

## Các lệnh quản trị `bench tlc config`

```bash
# Kiểm tra hợp lệ schema và toàn vẹn tham chiếu nội bộ (không ghi site, chạy được không cần site)
bench --site <site> tlc config validate

# Kiểm tra sai khác giữa site hiện tại và YAML (exit code 2 nếu có khác biệt)
bench --site <site> tlc config plan

# Áp dụng cấu hình declared lên site (chỉ ghi phần sai khác, an toàn dữ liệu)
bench --site <site> tlc config apply

# Xuất cấu hình site ra định dạng YAML chuẩn
bench --site <site> tlc config export <kind> [name]
```
