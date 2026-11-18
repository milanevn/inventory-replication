"""Nhật ký thay đổi (change_log) + các bảng dẫn xuất, lưu trong SQLite — NGUỒN SỰ THẬT của mỗi node.

Chủ sở hữu: TV1 (định dạng, lưu trữ) — TV4 dùng để phát hiện/khắc phục hỏng.

File: data/<node>/dstock.db, schema ở dstock/schema.sql. Mỗi entry được ghi trong MỘT transaction:
    INSERT change_log  +  cập nhật san_pham / phieu / phieu_ct / ton_kho
=> không bao giờ có trạng thái "đã ghi phiếu mà chưa trừ tồn" (tính nguyên tử — ACID).

Toàn vẹn — chuỗi hash (giống Git / blockchain thu nhỏ):
    hash(e) = sha256( lsn | req_id | kind | code | lines | note | product_name | unit | epoch | ts | prev_hash )
    e.prev_hash = hash(entry lsn-1), entry đầu dùng GENESIS.
=> Sửa 1 giá trị trong change_log làm vỡ hash của dòng đó; xóa/chèn dòng làm vỡ lsn hoặc prev_hash.
   Mất ĐUÔI / mất CẢ FILE thì phần còn lại vẫn hợp lệ — phải so đầu chuỗi với node khác
   (Node._primary_startup_check, ReplicationLink._check_head).

Toàn bộ entry cũng được giữ trong RAM (self.entries) — dữ liệu đồ án nhỏ, đọc nhanh, đơn giản.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .domain import NHAP, SANPHAM, Line
from .errors import CorruptLog

GENESIS = "0" * 64
SCHEMA = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")
_COLS = "lsn, req_id, kind, code, lines, note, product_name, unit, epoch, ts, prev_hash, hash"


@dataclass(frozen=True)
class Entry:
    lsn: int
    req_id: str
    kind: str
    code: str
    lines: tuple[Line, ...]
    note: str
    ts: float
    prev_hash: str
    hash: str = ""
    product_name: str = ""
    unit: str = ""
    epoch: int = 0

    # ---- hash ---------------------------------------------------------------
    def compute_hash(self) -> str:
        body = {
            "lsn": self.lsn,
            "req_id": self.req_id,
            "kind": self.kind,
            "code": self.code,
            "lines": [[l.sku, l.qty] for l in self.lines],
            "note": self.note,
            "product_name": self.product_name,
            "unit": self.unit,
            "epoch": self.epoch,
            "ts": round(self.ts, 6),
            "prev_hash": self.prev_hash,
        }
        canon = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()

    def sealed(self) -> "Entry":
        """Trả về bản sao đã điền hash."""
        return Entry(**{**self._fields(), "hash": self.compute_hash()})

    def is_intact(self) -> bool:
        return self.hash == self.compute_hash()

    # ---- (de)serialize ------------------------------------------------------
    def _fields(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    def to_json(self) -> str:
        d = asdict(self)
        d["lines"] = [[l["sku"], l["qty"]] for l in d["lines"]]
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def from_json(s: str) -> "Entry":
        d = json.loads(s)
        d["lines"] = tuple(Line(sku, int(qty)) for sku, qty in d["lines"])
        return Entry(**d)

    def to_row(self) -> tuple:
        lines = json.dumps([[l.sku, l.qty] for l in self.lines], ensure_ascii=False)
        return (self.lsn, self.req_id, self.kind, self.code, lines, self.note, self.product_name,
                self.unit, self.epoch, self.ts, self.prev_hash, self.hash)

    @staticmethod
    def from_row(r) -> "Entry":
        lsn, req_id, kind, code, lines, note, product_name, unit, epoch, ts, prev_hash, h = r
        return Entry(
            lsn=int(lsn), req_id=req_id, kind=kind, code=code,
            lines=tuple(Line(sku, int(q)) for sku, q in json.loads(lines)),
            note=note, ts=float(ts), prev_hash=prev_hash, hash=h,
            product_name=product_name, unit=unit, epoch=int(epoch),
        )


def verify_chain(entries: list[Entry], start_prev: str = GENESIS, start_lsn: int = 1) -> int:
    """Kiểm tra chuỗi. Trả về số entry hợp lệ liên tiếp tính từ đầu (== len nếu tất cả tốt)."""
    prev, expect = start_prev, start_lsn
    for i, e in enumerate(entries):
        if e.lsn != expect or e.prev_hash != prev or not e.is_intact():
            return i
        prev, expect = e.hash, expect + 1
    return len(entries)


def _replace_with_retry(src: Path, dst: Path, tries: int = 20, delay: float = 0.05) -> None:
    """os.replace trên Windows ném PermissionError nếu tiến trình/thread khác đang MỞ file đích
    (DB Browser, antivirus...). Thử lại vài lần trước khi bỏ cuộc."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(delay)


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False, timeout=5)
    try:
        conn.execute("PRAGMA synchronous=FULL")     # commit xong là đã nằm trên đĩa
        conn.executescript(SCHEMA)
    except BaseException:
        conn.close()            # file hỏng: phải đóng, nếu không Windows giữ khóa file -> không thay được
        raise
    return conn


def _apply_tables(conn: sqlite3.Connection, e: Entry) -> None:
    """Cập nhật các bảng dẫn xuất cho một entry (gọi BÊN TRONG transaction)."""
    if e.kind == SANPHAM:
        conn.execute("INSERT INTO san_pham(ma, ten, dvt) VALUES (?, ?, ?) "
                     "ON CONFLICT(ma) DO UPDATE SET ten = excluded.ten, dvt = excluded.dvt",
                     (e.code, e.product_name, e.unit))
        conn.execute("INSERT OR IGNORE INTO ton_kho(ma, sl) VALUES (?, 0)", (e.code,))
        return
    conn.execute("INSERT INTO phieu(lsn, so_phieu, loai, req_id, ghi_chu, ts) VALUES (?, ?, ?, ?, ?, ?)",
                 (e.lsn, e.code, e.kind, e.req_id, e.note, e.ts))
    for l in e.lines:
        conn.execute("INSERT INTO phieu_ct(lsn, ma, sl) VALUES (?, ?, ?)", (e.lsn, l.sku, l.qty))
        if e.kind == NHAP:
            conn.execute("INSERT OR IGNORE INTO san_pham(ma, ten, dvt) VALUES (?, ?, '')", (l.sku, l.sku))
            conn.execute("INSERT INTO ton_kho(ma, sl) VALUES (?, ?) "
                         "ON CONFLICT(ma) DO UPDATE SET sl = sl + excluded.sl", (l.sku, l.qty))
        else:
            # UPDATE (không UPSERT): SQLite kiểm CHECK(sl >= 0) trên dòng chèn TRƯỚC khi xét xung đột
            conn.execute("UPDATE ton_kho SET sl = sl - ? WHERE ma = ?", (l.qty, l.sku))


class OpLog:
    """Nhật ký thay đổi của một node: SQLite trên đĩa + bản sao các entry trong RAM."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: list[Entry] = []
        self.meta: dict[str, str] = {}
        self._conn: sqlite3.Connection | None = None

    # ---- đọc / kiểm tra -----------------------------------------------------
    def load(self) -> None:
        """Mở CSDL. Phát hiện hỏng -> raise CorruptLog (self.entries giữ phần TỐT phía trước)."""
        self.close()
        self.entries, self.meta = [], {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = _connect(self.path)
            rows = self._conn.execute(f"SELECT {_COLS} FROM change_log ORDER BY lsn").fetchall()
            self.meta = dict(self._conn.execute("SELECT key, value FROM meta").fetchall())
        except sqlite3.DatabaseError as exc:      # file không phải CSDL / trang dữ liệu hỏng
            self.close()
            raise CorruptLog(f"không mở được CSDL: {exc}", bad_lsn=1, good_count=0) from exc
        parsed: list[Entry] = []
        for r in rows:
            try:
                parsed.append(Entry.from_row(r))
            except (ValueError, TypeError, KeyError) as exc:
                self.entries = parsed[: verify_chain(parsed)]
                raise CorruptLog(f"entry lsn {r[0]} không đọc được: {exc}",
                                 bad_lsn=len(self.entries) + 1, good_count=len(self.entries)) from exc
        good = verify_chain(parsed)
        self.entries = parsed[:good]
        if good != len(parsed):
            raise CorruptLog(f"chuỗi hash vỡ tại lsn {good + 1}", bad_lsn=good + 1, good_count=good)

    def read_tables(self) -> tuple[dict[str, tuple[str, str]], dict[str, int]]:
        """(san_pham, ton_kho) đang lưu trong CSDL — để đối chiếu với trạng thái tính từ nhật ký."""
        conn = self._require()
        products = {ma: (ten, dvt) for ma, ten, dvt in conn.execute("SELECT ma, ten, dvt FROM san_pham")}
        stock = dict(conn.execute("SELECT ma, sl FROM ton_kho").fetchall())
        return products, stock

    # ---- ghi ----------------------------------------------------------------
    def append(self, e: Entry) -> None:
        if e.lsn != self.last_lsn + 1:
            raise ValueError(f"append lsn {e.lsn} nhưng last_lsn={self.last_lsn}")
        if e.prev_hash != self.last_hash or not e.is_intact():
            raise ValueError(f"entry lsn {e.lsn} sai hash")
        conn = self._require()
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(f"INSERT INTO change_log({_COLS}) VALUES ({','.join('?' * 12)})", e.to_row())
            _apply_tables(conn, e)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        self.entries.append(e)

    def rebuild_tables(self) -> None:
        """Dựng lại các bảng dẫn xuất từ change_log (khi bảng bị sửa lệch nhật ký)."""
        conn = self._require()
        conn.execute("BEGIN IMMEDIATE")
        try:
            for t in ("phieu_ct", "phieu", "ton_kho", "san_pham"):
                conn.execute(f"DELETE FROM {t}")
            for e in self.entries:
                _apply_tables(conn, e)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    def rewrite(self, entries: list[Entry]) -> None:
        """Thay TOÀN BỘ CSDL bằng `entries` (dùng khi phục hồi): dựng CSDL mới ở file tạm rồi
        rename đè (nguyên tử) — làm được cả khi file cũ hỏng tới mức không mở được."""
        tmp = self.path.with_name(self.path.name + ".tmp")
        if tmp.exists():
            tmp.unlink()
        conn = _connect(tmp)
        try:
            conn.execute("BEGIN IMMEDIATE")
            for k, v in self.meta.items():
                conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)", (k, v))
            for e in entries:
                conn.execute(f"INSERT INTO change_log({_COLS}) VALUES ({','.join('?' * 12)})", e.to_row())
                _apply_tables(conn, e)
            conn.execute("COMMIT")
        finally:
            conn.close()
        self.close()
        _replace_with_retry(tmp, self.path)
        self._conn = _connect(self.path)
        self.entries = list(entries)

    def set_meta(self, key: str, value: str) -> None:
        self._require().execute("INSERT INTO meta(key, value) VALUES (?, ?) "
                                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
        self.meta[key] = value

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _require(self) -> sqlite3.Connection:
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = _connect(self.path)
        return self._conn

    # ---- truy vấn -----------------------------------------------------------
    @property
    def last_lsn(self) -> int:
        return self.entries[-1].lsn if self.entries else 0

    @property
    def last_hash(self) -> str:
        return self.entries[-1].hash if self.entries else GENESIS

    def since(self, after_lsn: int, limit: int | None = None) -> list[Entry]:
        """Các entry có lsn > after_lsn (lsn bắt đầu từ 1 nên index = lsn-1)."""
        start = max(after_lsn, 0)
        end = len(self.entries) if limit is None else min(len(self.entries), start + limit)
        return self.entries[start:end]
