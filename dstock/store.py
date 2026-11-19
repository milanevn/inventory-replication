"""NodeStore — trạng thái của MỘT node: nhật ký thay đổi (SQLite) + trạng thái (RAM) + chỉ mục.

Hai đường ghi duy nhất:
  - write()            : chỉ bản chính. Kiểm tra nghiệp vụ -> cấp LSN -> ghi oplog -> áp dụng.
  - apply_replicated() : bản sao. Nhận entry đã có LSN từ nguồn -> kiểm tra thứ tự + hash -> ghi + áp dụng.
Mọi thao tác giữ self.lock => ghi được TUẦN TỰ HÓA tại mỗi node (không âm kho khi 2 client xuất cùng lúc).

Sau mỗi lần có entry mới, store gọi các listener (kênh nhân bản đi ra) — NGOÀI khóa.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, NamedTuple

from .domain import SANPHAM, Inventory, Voucher, normalize
from .errors import CorruptLog, InvalidVoucher, NodeCorrupt, NotPrimary
from .oplog import Entry, OpLog

log = logging.getLogger(__name__)

HEALTH_OK = "OK"
HEALTH_CORRUPT = "CORRUPT"
HEALTH_RECOVERING = "RECOVERING"


class AppendResult(NamedTuple):
    last_lsn: int
    last_hash: str     # "" nếu last_lsn = 0
    error: str         # "" | GAP | HASH_MISMATCH | DIVERGED | NODE_CORRUPT


@dataclass(frozen=True)
class StoreSnapshot:
    last_lsn: int
    last_hash: str
    digest: str
    stock: dict[str, int]
    last_apply_ts: float
    health: str
    detail: str
    products: dict[str, tuple[str, str]]
    epoch: int


class NodeStore:
    def __init__(self, node_id: str, data_dir: Path, is_primary: bool):
        self.node_id = node_id
        self.data_dir = Path(data_dir)
        self.is_primary = is_primary
        self.lock = threading.RLock()
        self.oplog = OpLog(self.data_dir / "dstock.db")
        self.inv = Inventory()
        self.req_index: dict[str, int] = {}
        self.code_index: dict[str, int] = {}      # số phiếu -> lsn (số phiếu là duy nhất)
        self.health = HEALTH_OK
        self.detail = ""
        self._listeners: list[Callable[[int], None]] = []

    # ------------------------------------------------------------------ khởi động
    def open(self) -> None:
        """Mở CSDL, kiểm chuỗi hash của change_log, dựng lại trạng thái bằng cách REPLAY nhật ký
        (khắc phục lùi dựa trên thao tác).

        - change_log hỏng: giữ phần tốt phía trước, đánh dấu CORRUPT và từ chối ghi. Việc kéo
          phần còn thiếu nằm ở dstock/recovery.py.
        - change_log tốt nhưng bảng dẫn xuất (ton_kho, san_pham) LỆCH nhật ký (vd: ai đó sửa tay
          số tồn): nhật ký là nguồn sự thật => dựng lại bảng từ nhật ký (khắc phục tiến), ghi log.
        """
        with self.lock:
            try:
                self.oplog.load()
                self.health, self.detail = HEALTH_OK, ""
            except CorruptLog as exc:
                self.health = HEALTH_CORRUPT
                self.detail = f"nhật ký hỏng: {exc} (giữ {exc.good_count} entry tốt)"
                log.error("[%s] %s", self.node_id, self.detail)
            self._rebuild()
            if self.health == HEALTH_OK and self.oplog.read_tables() != (self.inv.products, self.inv.stock):
                log.warning("[%s] bảng san_pham/ton_kho LỆCH nhật ký — dựng lại từ change_log", self.node_id)
                self.oplog.rebuild_tables()

    def close(self) -> None:
        with self.lock:
            self.oplog.close()

    def _rebuild(self) -> None:
        self.inv = Inventory()
        self.req_index = {}
        self.code_index = {}
        for e in self.oplog.entries:
            self._apply(e)

    def _apply(self, e: Entry) -> None:
        self.inv.apply(e.kind, list(e.lines), e.code, e.product_name, e.unit)
        self.req_index[e.req_id] = e.lsn
        if e.kind != SANPHAM:
            self.code_index[e.code] = e.lsn

    # ------------------------------------------------------------------ ghi (bản chính)
    def write(self, v: Voucher) -> tuple[Entry, bool]:
        """Trả về (entry, duplicate). Ném NotPrimary / NodeCorrupt / InvalidVoucher / InsufficientStock."""
        v = normalize(v)
        with self.lock:
            if not self.is_primary:
                raise NotPrimary(f"{self.node_id} không phải bản chính")
            if self.health != HEALTH_OK:
                raise NodeCorrupt(self.detail or self.health)
            if v.req_id in self.req_index:  # client gửi lại cùng req_id -> trả kết quả cũ
                return self.oplog.entries[self.req_index[v.req_id] - 1], True
            self.inv.validate(v)
            if v.kind != SANPHAM and v.code in self.code_index:
                raise InvalidVoucher(f"số phiếu {v.code} đã tồn tại")
            e = Entry(
                lsn=self.oplog.last_lsn + 1,
                req_id=v.req_id,
                kind=v.kind,
                code=v.code,
                lines=tuple(v.lines),
                note=v.note,
                ts=round(time.time(), 6),
                prev_hash=self.oplog.last_hash,
                product_name=v.product_name,
                unit=v.unit,
                epoch=self.epoch,
            ).sealed()
            self.oplog.append(e)
            self._apply(e)
        self._notify(e.lsn)
        return e, False

    # ------------------------------------------------------------------ ghi (bản sao)
    def apply_replicated(self, entries: list[Entry]) -> "AppendResult":
        """Áp dụng một lô entry từ nguồn. Trả về AppendResult(last_lsn, last_hash, error).

        - lsn <= last_lsn : đã có -> so hash: trùng thì bỏ qua (gửi lại không áp dụng 2 lần),
                            khác thì "DIVERGED" (hai chuỗi phân kỳ — không ghi đè im lặng).
        - lsn == last+1   : kiểm tra prev_hash + hash rồi áp dụng.
        - lsn >  last+1   : lỗ hổng -> dừng, trả "GAP"; nguồn sẽ gửi lại từ last_lsn+1.
        - lsn < 1         : entry không hợp lệ -> dừng, trả "INVALID_ENTRY".
        """
        applied = False
        err = ""
        with self.lock:
            if self.health != HEALTH_OK:
                return AppendResult(self.oplog.last_lsn, self._head_hash(), "NODE_CORRUPT")
            for e in entries:
                if e.lsn < 1:                       # dữ liệu từ mạng: không dùng làm chỉ mục âm
                    err = "INVALID_ENTRY"
                    break
                last = self.oplog.last_lsn
                if e.lsn <= last:
                    if self.oplog.entries[e.lsn - 1].hash != e.hash:
                        err = "DIVERGED"
                        break
                    continue
                if e.lsn != last + 1:
                    err = "GAP"
                    break
                if e.prev_hash != self.oplog.last_hash or not e.is_intact():
                    err = "HASH_MISMATCH"
                    break
                self.oplog.append(e)
                self._apply(e)
                applied = True
            result = AppendResult(self.oplog.last_lsn, self._head_hash(), err)
        if applied:
            self._notify(result.last_lsn)
        return result

    def _head_hash(self) -> str:
        return self.oplog.last_hash if self.oplog.entries else ""

    # ------------------------------------------------------------------ phục hồi (recovery.py dùng)
    def replace_log(self, entries: list[Entry]) -> None:
        """Thay toàn bộ oplog bằng `entries` đã kiểm chuỗi, dựng lại trạng thái, health -> OK."""
        with self.lock:
            self.oplog.rewrite(entries)
            self._rebuild()
            self.health, self.detail = HEALTH_OK, ""
        self._notify(self.oplog.last_lsn)

    def mark(self, health: str, detail: str = "") -> None:
        with self.lock:
            self.health, self.detail = health, detail

    # ------------------------------------------------------------------ meta (epoch, vai trò)
    @property
    def epoch(self) -> int:
        return int(self.oplog.meta.get("epoch", "0"))

    def get_meta(self, key: str, default: str = "") -> str:
        return self.oplog.meta.get(key, default)

    def set_meta(self, key: str, value: str) -> None:
        """Lưu bền vào bảng meta (vd: epoch, primary, members — dùng khi nâng bản chính)."""
        with self.lock:
            self.oplog.set_meta(key, value)

    # ------------------------------------------------------------------ đọc
    @property
    def last_lsn(self) -> int:
        return self.oplog.last_lsn

    def last_apply_ts(self) -> float:
        with self.lock:
            return self.oplog.entries[-1].ts if self.oplog.entries else 0.0

    def stock(self, skus: list[str] | None = None) -> dict[str, int]:
        with self.lock:
            snap = self.inv.snapshot()
        return {k: snap.get(k, 0) for k in skus} if skus else snap

    def snapshot(self) -> "StoreSnapshot":
        """Ảnh chụp NHẤT QUÁN (cùng một thời điểm) cho Admin.Status / GetStock."""
        with self.lock:
            return StoreSnapshot(
                last_lsn=self.oplog.last_lsn,
                last_hash=self._head_hash(),
                digest=self.inv.digest(),
                stock=self.inv.snapshot(),
                last_apply_ts=self.oplog.entries[-1].ts if self.oplog.entries else 0.0,
                health=self.health,
                detail=self.detail,
                products=dict(self.inv.products),
                epoch=self.epoch,
            )

    # ------------------------------------------------------------------ listener
    def add_listener(self, fn: Callable[[int], None]) -> None:
        self._listeners.append(fn)

    def _notify(self, lsn: int) -> None:
        for fn in self._listeners:
            try:
                fn(lsn)
            except Exception:  # listener lỗi không được làm hỏng đường ghi
                log.exception("[%s] listener lỗi", self.node_id)
