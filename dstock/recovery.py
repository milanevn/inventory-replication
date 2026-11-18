"""PHỤC HỒI khi dữ liệu bị tổn hại.

Đã có sẵn (dùng được ngay):
  - store.open() phát hiện oplog bị SỬA/xóa dòng giữa/ghi dở bằng chuỗi hash: giữ phần TỐT,
    đặt health=CORRUPT.
  - Mất ĐUÔI / mất CẢ FILE (chuỗi còn lại vẫn hợp lệ) ở bản chính: Node._primary_startup_check()
    và ReplicationLink._check_head() phát hiện bản sao đi trước -> đặt N1 CORRUPT (kể cả khi
    ĐANG CHẠY). Bản sao bị mất đuôi thì vô hại: kênh tự gửi bù.
  - Replication.FetchSince(after_lsn) trên node nguồn trả stream entry.
  - store.replace_log(entries) ghi đè oplog (ghi tạm rồi rename, tự thử lại khi Windows báo
    PermissionError) + dựng lại bảng tồn + health=OK.
  - store.snapshot() đọc (lsn, hash, digest, tồn) nhất quán; store.add_listener(fn) = móc "sau mỗi
    entry mới" (dùng cho checkpoint) — KHÔNG cần sửa store.py.

Thread nền: BẮT BUỘC dùng node.spawn(fn, "tên") và thoát vòng khi node.stopping được bật
(`while not node.stopping.wait(0.3): ...`) — không thì dừng node có thể treo cả tiến trình.

Việc cần làm (TODO; xem docs/architecture.md, mục Quyết định thiết kế) — chỉ sửa recovery.py + checkpoint.py:
  1. Vòng phục hồi chạy NỀN SUỐT ĐỜI node (không chỉ lúc khởi động): thấy health CORRUPT thì
     cách ly file (*.corrupt-<ts>), hỏi Status MỌI nguồn trong cfg.recovery_sources[node_id],
     chọn nguồn OK có last_lsn LỚN NHẤT (hòa: theo thứ tự danh sách), FetchSince(len(phần tốt)),
     kiểm chuỗi nối tiếp phần tốt (oplog.verify_chain), replace_log. Mọi nguồn chết: giữ CORRUPT,
     thử lại sau. Không chặn on_startup quá ~1 giây.
  2. SCRUB khi đang chạy: mỗi ~1s đọc lại file và so với RAM. BẮT BUỘC làm trong `store.lock`:
     append() ghi file TRƯỚC rồi mới cập nhật RAM — đọc ngoài khóa sẽ thấy file "dài hơn" RAM,
     tưởng lệch rồi ghi đè => làm MẤT entry vừa fsync. File lệch thì ghi lại từ RAM (khắc phục tiến).
  3. Checkpoint (state-based): lưu snapshot mỗi cfg.snapshot_every entry (qua add_listener). Khi
     khởi động: replay xong so digest với checkpoint để kiểm tra chéo. (Cắt bớt oplog nhờ checkpoint
     là tùy chọn — cần sửa store.py, báo trong nhóm trước.)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .store import HEALTH_CORRUPT

if TYPE_CHECKING:
    from .node import Node

log = logging.getLogger(__name__)


def on_startup(node: "Node") -> None:
    """Gọi sau khi store.open() và server đã chạy (để node khác gọi được tới mình)."""
    if node.store.health == HEALTH_CORRUPT:
        # TODO: phục hồi từ node.cfg.recovery_sources[node.id] — xem fetch_from().
        log.error("[%s] dữ liệu hỏng, CHƯA có phục hồi tự động. Node từ chối ghi.", node.id)


def fetch_from(node: "Node", source_id: str, after_lsn: int) -> list:
    """Kéo các entry có lsn > after_lsn từ `source_id`. Trả list[Entry].

    TODO: stub = node.replication_stub(source_id);
               [entry_from_pb(m) for m in stub.FetchSince(pb.FetchRequest(...), timeout=...)]
    """
    raise NotImplementedError("phục hồi chưa được cài đặt (dstock/recovery.py)")
