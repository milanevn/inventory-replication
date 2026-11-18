"""Bộ khung test: dựng cụm 4 node NGAY TRONG tiến trình pytest (cổng ngẫu nhiên, thư mục tạm).

Dùng qua fixture `make_cluster` trong conftest.py:

    def test_x(make_cluster):
        c = make_cluster()                       # mặc định: lan truyền nhanh (FAST_LINKS)
        c = make_cluster(links=SPEC_LINKS)       # đúng đề: interval 1s, count 3 (test TV3)
        c.client.nhap("PN1", parse_lines(["SP01:5"]))
        assert c.wait_converged()
        c.stop("N3"); ...; c.start("N3")
        c.corrupt_entry("N3", lsn=2)
"""
from __future__ import annotations

import json
import socket
import sqlite3
import time
from pathlib import Path
from typing import Callable

from dstock.client import DStockClient, parse_lines
from dstock.config import ClusterConfig, parse_config
from dstock.node import Node

NODE_IDS = ("N1", "N2", "N3", "N4")

# Mặc định cho test KHÔNG nói về trigger: lan truyền nhanh để test không phụ thuộc n
# (count=1, interval=0.2s) — nhờ vậy test vẫn đúng cả TRƯỚC và SAU khi TV3 làm trigger.
FAST_LINKS = [
    {"from": "N1", "to": "N2", "mode": "sync"},
    {"from": "N1", "to": "N3", "mode": "interval", "param": 0.2},
    {"from": "N2", "to": "N4", "mode": "count", "param": 1},
]

# Tham số "đúng đề" cho test của TV3: interval 1 giây, count 3 lần.
SPEC_LINKS = [
    {"from": "N1", "to": "N2", "mode": "sync"},
    {"from": "N1", "to": "N3", "mode": "interval", "param": 1},
    {"from": "N2", "to": "N4", "mode": "count", "param": 3},
]

# Giống cluster.toml: kéo theo CHIỀU CẠNH (N4 chỉ từ N2); bản chính N1 kéo từ bản sao mới nhất.
RECOVERY_SOURCES = {"N1": ["N2", "N3", "N4"], "N2": ["N1"], "N3": ["N1"], "N4": ["N2"]}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until(pred: Callable[[], bool], timeout: float = 5.0, interval: float = 0.05) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(interval)
    return pred()


class Cluster:
    _seq = 0

    def __init__(self, tmp_path: Path, links: list[dict] | None = None, snapshot_every: int = 50):
        Cluster._seq += 1                      # mỗi cụm một thư mục riêng (1 test tạo được nhiều cụm)
        raw = {
            "primary": "N1",
            "data_dir": str(tmp_path / f"cluster{Cluster._seq}"),
            "snapshot_every": snapshot_every,
            "nodes": {nid: {"host": "127.0.0.1", "port": free_port()} for nid in NODE_IDS},
            "links": links if links is not None else FAST_LINKS,
            "recovery_sources": RECOVERY_SOURCES,
        }
        self.cfg: ClusterConfig = parse_config(raw)
        self.nodes: dict[str, Node] = {}
        self.client = DStockClient(self.cfg, timeout=3.0)

    # ---- vòng đời -----------------------------------------------------------
    def start(self, *ids: str) -> "Cluster":
        # Mặc định bật bản sao TRƯỚC, bản chính SAU: bản chính khi khởi động hỏi các bản sao
        # (kiểm tra mất dữ liệu) — bản sao chưa chạy thì mỗi lần hỏi tốn tới timeout.
        for nid in ids or tuple(reversed(NODE_IDS)):
            self.nodes[nid] = Node(nid, self.cfg).start()
        return self

    def stop(self, nid: str) -> None:
        self.nodes.pop(nid).stop()

    def restart(self, nid: str) -> None:
        self.stop(nid)
        self.start(nid)

    def close(self) -> None:
        for nid in list(self.nodes):
            self.stop(nid)
        self.client.close()

    # ---- tiện ích -----------------------------------------------------------
    def nhap(self, code: str, *lines: str):
        return self.client.nhap(code, parse_lines(list(lines)))

    def xuat(self, code: str, *lines: str):
        return self.client.xuat(code, parse_lines(list(lines)))

    def lsn(self, nid: str) -> int:
        return self.nodes[nid].store.last_lsn

    def digest(self, nid: str) -> str:
        return self.nodes[nid].store.inv.digest()

    def health(self, nid: str) -> str:
        return self.nodes[nid].store.health

    def link(self, src: str, dst: str):
        return self.nodes[src].link_to(dst)

    def wait_converged(self, ids=NODE_IDS, timeout: float = 5.0) -> bool:
        def ok():
            alive = [n for n in ids if n in self.nodes]
            return len({(self.lsn(n), self.digest(n)) for n in alive}) == 1
        return wait_until(ok, timeout)

    def wait_lsn(self, nid: str, lsn: int, timeout: float = 5.0) -> bool:
        return wait_until(lambda: nid in self.nodes and self.lsn(nid) >= lsn, timeout)

    # ---- gây hỏng dữ liệu ---------------------------------------------------
    def db_path(self, nid: str) -> Path:
        return self.cfg.node_data_dir(nid) / "dstock.db"

    def _sql(self, nid: str, sql: str, params: tuple = ()) -> list:
        """Chạy SQL trực tiếp trên CSDL của node (node phải ĐANG TẮT, trừ test "hỏng khi đang chạy")."""
        conn = sqlite3.connect(str(self.db_path(nid)), isolation_level=None)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def corrupt_entry(self, nid: str, lsn: int) -> None:
        """Sửa số lượng dòng hàng đầu của entry `lsn` trong change_log (giữ nguyên hash => chuỗi vỡ)."""
        (lines,), = self._sql(nid, "SELECT lines FROM change_log WHERE lsn = ?", (lsn,))
        d = json.loads(lines)
        d[0][1] += 1
        self._sql(nid, "UPDATE change_log SET lines = ? WHERE lsn = ?", (json.dumps(d), lsn))

    def delete_entry(self, nid: str, lsn: int) -> None:
        self._sql(nid, "DELETE FROM change_log WHERE lsn = ?", (lsn,))

    def truncate(self, nid: str, keep: int) -> None:
        """Giữ `keep` entry đầu (mô phỏng chép đè bằng bản sao lưu CŨ). Chuỗi phần còn lại VẪN hợp lệ."""
        self._sql(nid, "DELETE FROM change_log WHERE lsn > ?", (keep,))

    def tamper_stock(self, nid: str, sku: str, qty: int) -> None:
        """Sửa tay số tồn trong bảng ton_kho (bảng dẫn xuất) — nhật ký vẫn đúng."""
        self._sql(nid, "UPDATE ton_kho SET sl = ? WHERE ma = ?", (qty, sku))

    def delete_db(self, nid: str) -> None:
        self.db_path(nid).unlink()
