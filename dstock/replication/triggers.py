"""Điều kiện kích hoạt gửi của một kênh nhân bản.

Chủ sở hữu: TV3.

Kênh nhân bản (link.py) gọi `due(pending, since_last_flush, oldest_age)` mỗi khi có entry mới
hoặc mỗi `wait_timeout()` giây. Trả True => kênh gửi TOÀN BỘ phần đang chờ tại thời điểm đó.

    pending          : số entry nguồn có mà đích chưa xác nhận (> 0 khi được gọi)
    since_last_flush : số giây kể từ lần gửi gần nhất
    oldest_age       : số giây entry chờ CŨ NHẤT đã chờ

Ngữ nghĩa đã chốt (docs/architecture.md, mục Quyết định thiết kế):
    interval n giây : mỗi cập nhật tới đích khoảng n giây SAU KHI được ghi ở nguồn; các cập nhật
                      đến trong khoảng đó đi cùng lô  =>  gửi khi oldest_age >= n.
                      (KHÔNG dùng since_last_flush: rảnh lâu rồi ghi thì phiếu sẽ đi NGAY — sai đề.)
    count n lần     : gửi khi đã dồn đủ n entry  =>  pending >= n.

Đổi n lúc đang chạy: Admin.SetLinkParam -> link.set_param() -> trigger.set_param() -> kênh
được đánh thức để hỏi due() lại ngay.
"""
from __future__ import annotations

import threading

from ..config import LinkConfig


class Trigger:
    mode = ""

    def __init__(self, param: float):
        self._lock = threading.Lock()
        self._param = float(param)

    @property
    def param(self) -> float:
        with self._lock:
            return self._param

    def set_param(self, value: float) -> None:
        if value <= 0:
            raise ValueError("param phải > 0")
        with self._lock:
            self._param = float(value)

    def due(self, pending: int, since_last_flush: float, oldest_age: float) -> bool:
        raise NotImplementedError

    def wait_timeout(self) -> float:
        """Kênh tự thức dậy sau tối đa bấy nhiêu giây để hỏi lại due()."""
        return 0.2


class ImmediateTrigger(Trigger):
    """Kênh "sync" (N1→N2): có gì ĐẨY NGAY, không chờ xác nhận. param: không dùng."""
    mode = "sync"

    def due(self, pending: int, since_last_flush: float, oldest_age: float) -> bool:
        return pending > 0


class IntervalTrigger(Trigger):
    """Kênh interval (N1→N3): cập nhật tới đích sau n giây. param = n giây."""
    mode = "interval"

    def due(self, pending: int, since_last_flush: float, oldest_age: float) -> bool:
        # TODO(TV3): gửi khi entry chờ cũ nhất đã chờ đủ n giây (oldest_age >= self.param).
        #   Cân nhắc: wait_timeout() có nên phụ thuộc n (n = 0.5s thì thức 0.2s là quá thô)?
        #   Bật tests/acceptance/test_tv3_triggers.py để kiểm tra.
        return pending > 0  # TẠM THỜI gửi ngay để cụm chạy được ở M0


class CountTrigger(Trigger):
    """Kênh count (N2→N4): gửi khi đã dồn đủ n lần cập nhật. param = n."""
    mode = "count"

    def due(self, pending: int, since_last_flush: float, oldest_age: float) -> bool:
        # TODO(TV3): chỉ gửi khi pending >= n (n = int(self.param)).
        #   Cân nhắc: đổi n từ 10 xuống 3 trong lúc đang dồn 5 => gửi ngay.
        #   "1 lần cập nhật" = 1 phiếu = 1 entry (docs/architecture.md).
        return pending > 0  # TẠM THỜI gửi ngay để cụm chạy được ở M0


TRIGGERS: dict[str, type[Trigger]] = {
    "sync": ImmediateTrigger,
    "interval": IntervalTrigger,
    "count": CountTrigger,
}


def make_trigger(cfg: LinkConfig) -> Trigger:
    return TRIGGERS[cfg.mode](cfg.param)
