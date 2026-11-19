<!-- Tiêu đề PR theo mẫu: feat(triggers): count trigger gửi khi đủ n thao tác -->

## Thay đổi

<!-- 1-3 câu: làm gì, vì sao. Có issue thì ghi "Closes #12". -->

## Kiểm tra

- [ ] `pytest` toàn bộ xanh trên máy mình
- [ ] Test của mình chạy 3 lần liên tiếp đều xanh
- [ ] Đã xóa dấu `@pytest.mark.todo` của các test đã làm xong
- [ ] Đã thử bằng GUI hoặc CLI (ghi lệnh ở mục dưới)
- [ ] Chỉ sửa file của module đang làm; file dùng chung thì đã báo trong nhóm
- [ ] Nếu sửa `proto/`: đã chạy `python scripts/gen_proto.py` và commit file sinh ra

## Cách thử

```
python scripts/run_cluster.py --clean --gui
...
```
