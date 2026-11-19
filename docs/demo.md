# Kịch bản demo

Khoảng 12 phút. Mục tiêu là cho thấy đủ ba kiểu lan truyền, phục hồi khi dữ liệu hỏng, và cách cụm xử lý khi node chết.

## Chuẩn bị

- Chạy trên một máy: `python scripts/run_cluster.py --clean --gui`.
- Chạy trên LAN: mỗi máy `python scripts/run_cluster.py Nx --config cluster.lan.toml`, máy client mở `python -m dstock.gui --config cluster.lan.toml`.
- Đặt GUI, một cửa sổ CLI và DB Browser for SQLite cạnh nhau.
- Có sẵn video dự phòng. Demo LAN lỗi thì chuyển về chạy trên một máy.

## Phần 1: nghiệp vụ và lan truyền

1. `cli seed`. Cả 4 node có cùng danh mục sản phẩm và số tồn.
2. Xuất `SP01:999`, rồi gửi lại một phiếu trùng số phiếu. Cả hai đều bị từ chối.
3. Xuất vài phiếu liên tiếp. N2 bằng N1 gần như ngay lập tức.
4. Đặt n = 10 cho N3. Ghi một phiếu, đợi 4 giây, ghi thêm một phiếu. Khoảng 10 giây sau phiếu đầu, cả hai phiếu cùng tới N3.
5. Đặt n = 3 cho N4, ghi từng phiếu. N4 chỉ thay đổi sau mỗi 3 phiếu.
6. Đặt n = 5 cho N4, ghi 2 phiếu, rồi đổi n xuống 2. N4 nhận ngay 2 phiếu đang chờ.

## Phần 2: dữ liệu bị tổn hại

7. Crash N3, ghi 3 phiếu, bật lại N3. N3 tự bắt kịp.
8. Tắt N4, sửa một số trong `change_log` của `data/N4/dstock.db` (bằng DB Browser hoặc `scripts/lam_hong.py`), bật lại. N4 báo `CORRUPT` rồi tự phục hồi từ N2. Dùng DB Browser thì bấm Write Changes và đóng file trước khi bật lại node, nếu không node không mở hoặc không thay được CSDL.
9. Tắt N3, sửa số tồn trong `ton_kho`, bật lại. N3 dựng lại bảng từ nhật ký, số tồn đúng như cũ.
10. Tắt N1, xóa vài dòng cuối trong `change_log` của N1, bật lại. N1 thấy bản sao đi trước mình nên chuyển `CORRUPT`, không cấp lại LSN cũ, rồi phục hồi từ node mới nhất.

## Phần 3: node chết

11. Tắt N3 rồi ghi. Vẫn ghi được vì 3/4 vẫn là đa số. Bật lại N3, nó tự bắt kịp.
12. Tắt N2 và N3. N1 báo không đủ đa số và từ chối ghi, đọc vẫn được. Giải thích: hai node không phải đa số; chặn như vậy để không có hai bản chính.
13. Bật lại N2, N3, rồi tắt riêng N1. GUI chuyển sang chỉ đọc ở node mới nhất. Giải thích vì sao không tự bầu dù vẫn còn đa số.
14. `cli promote N2 --exclude N1` (hoặc dùng nút trên GUI), rồi ghi. N2 thành bản chính với epoch 1; N3, N4 nhận dữ liệu.
15. Bật lại N1. N1 tự hạ cấp thành bản sao; entry chưa kịp lan đi (nếu có) nằm trong `data/N1/orphans-*.jsonl`.
16. Chỉ nói, không cần làm: khi còn một node thì `promote` bị từ chối và cụm chỉ đọc.

## Câu hỏi hay gặp

"Sao không cho tự bầu?" Timeout không phân biệt được node chết với mạng đứt. Bầu sai thì có hai bản chính cùng ghi. Nhóm chọn cách an toàn là để người quản trị xác nhận rồi nâng tay (xem [architecture.md](architecture.md#không-bầu-cử-tự-động)).

"Sao 1→2 không chờ xác nhận?" Nếu chờ thì N2 chết là N1 cũng không ghi được.

## Còn phải bổ sung

- Lời thuyết minh cho từng bước.
- Ảnh chụp GUI ở các bước chính.
- Quay video dự phòng sau lần tổng duyệt cuối.
