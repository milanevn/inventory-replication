# Vận hành

Cách chạy cụm, xem trạng thái và xử lý khi có sự cố.

## Chạy cả cụm trên một máy

```bash
python scripts/run_cluster.py --clean --gui     # --clean xóa dữ liệu cũ, --gui mở bảng điều khiển
```

Ctrl+C để tắt. Nếu lỡ đóng terminal mà các node vẫn chạy thì dùng:

```bash
python scripts/stop_cluster.py
```

## Chạy mỗi máy một node

1. Sửa `cluster.lan.toml`: đặt `host` là IP thật của từng máy (xem bằng `ipconfig`). Cả nhóm dùng chung một file này.
2. Mở firewall cho cổng của node trên máy đó, ví dụ máy chạy N2 (PowerShell quyền admin):
   ```powershell
   New-NetFirewallRule -DisplayName "DStock 7002" -Direction Inbound -Protocol TCP -LocalPort 7002 -Action Allow
   ```
3. Trên máy chạy N2:
   ```bash
   python scripts/run_cluster.py N2 --config cluster.lan.toml
   ```
4. Trên máy client:
   ```bash
   python -m dstock.gui --config cluster.lan.toml
   python -m dstock.cli --config cluster.lan.toml status     # phải thấy đủ 4 node
   ```

## Lệnh thường dùng

```bash
python -m dstock.cli seed                        # khai báo 3 sản phẩm, nhập tồn đầu kỳ
python -m dstock.cli sanpham SP04 "Bút chì" --dvt cây
python -m dstock.cli nhap PN001 SP01:10 SP02:5
python -m dstock.cli xuat PX001 SP01:3
python -m dstock.cli ton --node N4               # đọc tồn ở N4
python -m dstock.cli status                      # vai trò, epoch, LSN, digest, kênh của 4 node
python -m dstock.cli set-n N4 5                  # kênh vào N4 gửi sau 5 thao tác
python -m dstock.cli set-n N3 10                 # kênh vào N3 gửi sau 10 giây
python -m dstock.cli fault N1 N3 --partition     # cắt kênh N1->N3
python -m dstock.cli crash N3                    # tắt N3
python -m dstock.node --id N3                    # bật lại N3
```

Log của từng node nằm ở `data/logs/<id>.log`, CSDL ở `data/<id>/dstock.db`. Mở CSDL bằng DB Browser for SQLite để xem các bảng.

## Khi node chết

Cụm có 4 thành viên, đa số là 3. Hệ thống không bao giờ tự bầu bản chính (lý do ở [architecture.md](architecture.md#không-bầu-cử-tự-động)).

| Tình huống | Còn sống | Ghi | Đọc | Làm gì |
|---|---|---|---|---|
| Bình thường | 4 | ở N1 | mọi node | |
| Một bản sao chết (N2, N3 hoặc N4) | 3 | ở N1 | được | Không cần làm gì. Bật lại thì node tự bắt kịp. Riêng N2 chết thì N4 đứng yên tới khi N2 lên lại |
| N1 chết, các node khác còn | 3 | dừng | ở node mới nhất | Bật lại N1 nếu được. Bắt buộc ghi ngay thì `promote <node mới nhất> --exclude N1` |
| Hai bản sao chết, N1 còn | 2 | `NO_QUORUM` | được | Bật lại một node. Bắt buộc ghi ngay thì thu hẹp thành viên: `promote N1 --exclude Nx Ny` |
| N1 và một bản sao chết | 2 | dừng | ở node mới nhất | Bật lại node. Bắt buộc ghi ngay thì `promote <node mới nhất> --exclude N1 Nx` |
| Chỉ còn một node | 1 | không | ở node còn lại | Không ghi được; `promote` sẽ bị từ chối |

"Node mới nhất" là node có LSN lớn nhất trong `cli status`. Nếu chọn sai, `promote` sẽ từ chối và báo node nào mới hơn.

Trước khi nâng, phải chắc các node trong `--exclude` đã chết thật (đã tắt tiến trình hoặc tắt máy). Nếu node đó vẫn trả lời, `promote` sẽ từ chối.

Sau khi nâng:

- Node cũ bật lại sẽ tự thành bản sao và được nhận lại vào cụm.
- Nếu bản chính cũ có entry chưa kịp lan đi, chúng nằm trong `data/<id>/orphans-<ts>.jsonl`. Xem file này và nhập lại bằng tay nếu cần.
- Muốn trả vai trò cho N1 thì đợi N1 bắt kịp rồi chạy `promote N1`.

## Khi dữ liệu bị hỏng

Node phát hiện hỏng sẽ chuyển `CORRUPT`, từ chối ghi và tự kéo lại dữ liệu từ nguồn. File hỏng được đổi tên và giữ lại trong thư mục của node.

| Hiện tượng | Nguyên nhân thường gặp | Hệ thống làm gì |
|---|---|---|
| Node lên lại thiếu dữ liệu | Node tắt lâu | Kênh gửi bù phần thiếu |
| `CORRUPT`, log báo sai hash | Ai đó sửa `change_log` | Cách ly CSDL, kéo lại từ nguồn |
| `CORRUPT` ngay khi mở CSDL | File hỏng, bị xóa | Như trên |
| Bản chính `CORRUPT`, log báo có bản sao đi trước | N1 mất đuôi dữ liệu | N1 kéo lại từ bản sao có LSN lớn nhất |
| Số tồn trong `ton_kho` sai, nhật ký vẫn đúng | Sửa tay bảng tồn | Lần khởi động sau tự dựng lại bảng |
| Kênh `DIVERGED` | Hai chuỗi rẽ nhánh | Không tự sửa; kiểm tra log rồi xử lý tay |

Nếu nguồn phục hồi cũng đang chết (ví dụ N4 hỏng trong lúc N2 tắt), node giữ `CORRUPT` và tự thử lại cho tới khi nguồn lên.

## Sự cố thường gặp

- Cổng 7001 đến 7004 bị chiếm: còn tiến trình node cũ. Chạy `python scripts/stop_cluster.py`, hoặc `netstat -ano | findstr 700` để tìm rồi tắt.
- Node vừa bật lại mà CLI báo `UNAVAILABLE`: kênh gRPC đang kết nối lại, đợi khoảng một giây rồi thử lại.
- In tiếng Việt ra console bị lỗi: dùng Python 3.12 và chạy qua các script trong repo, chúng đã chuyển console sang UTF-8.
- Máy khác không thấy node: kiểm tra IP trong `cluster.lan.toml`, firewall, và hai máy có cùng mạng không.
