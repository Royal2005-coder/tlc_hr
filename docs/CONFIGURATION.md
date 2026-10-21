# Cấu hình khai báo (customizing) của TLC HRM

Mọi cấu hình TLC thêm vào Frappe được khai báo trong `tlc_hr/customizing/**/*.yaml`, gồm vai trò, trường thêm, quyền, workflow duyệt, mẫu email, thẻ số liệu, biểu đồ, workspace, ca làm việc, địa điểm chấm công, loại nghỉ, loại tăng ca, tham số lương Việt Nam và tài khoản.

- **Nguồn duy nhất.** YAML là nguồn duy nhất, được git quản lý và đi theo image.
- **Áp dụng tự động.** `bench migrate` áp YAML lên site qua hook `after_migrate`. Cách áp là idempotent: chỉ ghi phần khác.
- **Data contract.** Mỗi file được kiểm tra bằng data contract (`tlc_hr/contracts/customizing.py`, Pydantic strict, không nhận khoá lạ).

## Đối chiếu với SAP

| SAP | TLC trên Frappe |
|---|---|
| DDIC (bảng/trường) | DocType JSON trong `tlc_hr/tlc_hr/doctype/` (doctype riêng TLC) + `customizing/custom_fields.yaml` (trường thêm vào doctype chuẩn) |
| Customizing SPRO/IMG | `tlc_hr/customizing/*.yaml` |
| SE16 xem cấu hình | Desk Frappe hoặc `bench --site <site> tlc config plan` |
| Transport STMS | Commit git → build image → `bench migrate` (áp YAML) |
| BAdI / user exit | `hooks.py`: `doc_events`, `permission_query_conditions`, `has_permission` → `tlc_hr/interface/` |
| Transaction / report ABAP | Lệnh `bench tlc …`, Script/Query Report của Frappe |
| RFC / BAPI | REST `/api/resource/<DocType>`, `/api/method/<hàm>` (frappe-client làm SDK) |

## Lệnh

```
bench --site <site> tlc config validate                 # kiểm YAML theo contract và tham chiếu chéo; không ghi
bench --site <site> tlc config plan                     # liệt kê khác biệt site ↔ YAML; exit 2 nếu có khác biệt
bench --site <site> tlc config apply                    # ghi phần khác biệt
bench --site <site> tlc config export-workflow "<tên>"  # workflow sửa trên desk → YAML để đưa về git
bench --site <site> tlc doctor                          # kiểm tra vận hành (ca + địa điểm, trưởng nhà máy, người duyệt, tài khoản, kỳ công)
bench --site <site> tlc seed run|reset-leave|reset-overtime|reset-periods   # dữ liệu demo (reset chỉ trên site allow_tests)
```

Trên k3s: `kubectl -n tlc-hr exec deploy/backend -- bench --site tlc-hr.local tlc config plan`.

## Các loại khai báo

Mỗi file có dạng `version: 1`, `kind: <loại>`, `description: …`, rồi đến các mục của loại đó.

| kind | Khoá | Ghi vào Frappe |
|---|---|---|
| `roles` | `roles: [{name, desk_access, home_page}]` | Role |
| `custom_fields` | `custom_fields: [{doctype, fields: [{fieldname, fieldtype, label, insert_after, options, permlevel, read_only, …}]}]` | Custom Field |
| `permissions` | `permissions: [{doctype, role, permlevel, rights}]`, `rights` là chữ cái `r w c d s x a` (đọc, ghi, tạo, xoá, submit, huỷ, sửa đổi) | Custom DocPerm |
| `workflow` | `workflow: {name, doctype, states: [{state, doc_status, allow_edit, style}], transitions: [{from, action, to, allowed: [vai trò], condition, allow_self_approval}]}` | Workflow, Workflow State, Workflow Action Master |
| `email_templates` | `email_templates: [{name, subject, html, hr_setting}]` | Email Template (+ trỏ HR Settings) |
| `dashboards` | `number_cards: [{name, doctype, color, function, field, filters, dynamic_filters}]`, `charts: [{name, chart_type, document_type, type, filters, …}]` | Number Card, Dashboard Chart |
| `workspaces` | `shortcuts: [{label, type, link_to, url, doc_view, color, stats_filter, format}]`, `workspaces: [{title, roles, icon, sequence, cards, charts, shortcuts, quick_list}]` | Workspace |
| `records` | `records: [{doctype, name, values, on_create, tables}]`. Bỏ `name` để ghi doctype single | Bản ghi cấu hình bất kỳ: Shift Type, Shift Location, HR Settings, Leave Type, Overtime Type, VN Payroll Settings… |
| `accounts` | `accounts: {account_types: {số TK: loại}, company_defaults: {trường Company: số TK}}` | Account, Company |

Một vài lưu ý:
- `url` của shortcut có thể chứa `{year}` (năm hiện tại).
- Workspace tham chiếu thẻ, biểu đồ và shortcut theo tên; tên sai bị báo lỗi khi validate.
- Một workflow chỉ được dùng trạng thái đã khai báo.

## Quy trình thay đổi cấu hình

1. Sửa YAML, hoặc chỉnh trên desk rồi lấy về bằng `tlc config export-workflow`.
2. Chạy `tlc config validate` và unit test (`tests/unit/test_customizing.py`). CI chạy lại hai bước này khi push.
3. Chạy `tlc config plan` trên site thử và đọc diff.
4. Commit, build image, `bench migrate` (lệnh này tự `apply`).
5. Chạy `tlc doctor`.

Thay đổi trực tiếp trên desk mà không đưa về YAML sẽ bị `migrate` sau ghi đè. `tlc config plan` hoặc `tlc doctor` sẽ báo trước.

## Tham số luật Việt Nam

`records.yaml` → `VN Payroll Settings` chứa lương cơ sở, tỷ lệ bảo hiểm, giảm trừ gia cảnh, lương tối thiểu vùng và ngày hiệu lực. Unit test so giá trị này với `tlc_hr/vn/statutory.py`, nơi công thức lương đọc tham số. Khi luật đổi, thêm dòng có ngày hiệu lực; không sửa đè giá trị cũ, để phiếu lương cũ vẫn tính lại đúng.
