"""Ứng dụng cập nhật lan truyền, dữ liệu nhập–xuất–tồn (đề tài 8)."""

import sys

# config.py dùng tomllib (có từ Python 3.11). Báo rõ ngay thay vì để lỗi import khó hiểu.
if sys.version_info < (3, 11):
    raise RuntimeError(
        f"Cần Python 3.11 trở lên, đang chạy {sys.version.split()[0]}. "
        "Tạo lại .venv bằng bản mới hơn, ví dụ: py -3.12 -m venv .venv"
    )

__version__ = "0.1.0"
