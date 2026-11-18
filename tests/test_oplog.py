import json
import sqlite3

import pytest

from dstock.domain import Line
from dstock.errors import CorruptLog
from dstock.oplog import GENESIS, Entry, OpLog


def make_entries(n):
    out, prev = [], GENESIS
    for i in range(1, n + 1):
        e = Entry(i, f"r{i}", "NHAP", f"PN{i}", (Line("SP01", i),), "", 1000.0 + i, prev).sealed()
        out.append(e)
        prev = e.hash
    return out


def write_log(path, n):
    log = OpLog(path)
    log.load()
    for e in make_entries(n):
        log.append(e)
    return log


def sql(path, q, params=()):
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        return conn.execute(q, params).fetchall()
    finally:
        conn.close()


def test_ghi_va_doc_lai(tmp_path):
    write_log(tmp_path / "n.db", 5).close()
    log = OpLog(tmp_path / "n.db")
    log.load()
    assert log.last_lsn == 5
    assert [e.lsn for e in log.since(2)] == [3, 4, 5]
    assert [e.lsn for e in log.since(0, limit=2)] == [1, 2]
    log.close()


def test_bang_dan_xuat_ghi_cung_transaction(tmp_path):
    log = write_log(tmp_path / "n.db", 3)                 # nhập 1 + 2 + 3
    products, stock = log.read_tables()
    assert stock == {"SP01": 6} and products == {"SP01": ("SP01", "")}
    assert sql(tmp_path / "n.db", "SELECT COUNT(*) FROM phieu")[0][0] == 3
    log.close()


def test_append_sai_thu_tu_bi_tu_choi(tmp_path):
    log = OpLog(tmp_path / "n.db")
    log.load()
    with pytest.raises(ValueError):
        log.append(make_entries(2)[1])
    log.close()


def test_sua_so_luong_trong_change_log_lam_vo_chuoi(tmp_path):
    p = tmp_path / "n.db"
    write_log(p, 5).close()
    sql(p, "UPDATE change_log SET lines = ? WHERE lsn = 3", (json.dumps([["SP01", 999]]),))
    log = OpLog(p)
    with pytest.raises(CorruptLog) as ei:
        log.load()
    assert ei.value.bad_lsn == 3
    assert log.last_lsn == 2          # giữ phần tốt phía trước
    log.close()


def test_xoa_mot_dong_bi_phat_hien(tmp_path):
    p = tmp_path / "n.db"
    write_log(p, 4).close()
    sql(p, "DELETE FROM change_log WHERE lsn = 2")
    with pytest.raises(CorruptLog) as ei:
        OpLog(p).load()
    assert ei.value.bad_lsn == 2


def test_file_khong_phai_csdl(tmp_path):
    p = tmp_path / "n.db"
    p.write_bytes(b"rac rac rac" * 200)                 # vd: file bị ghi đè / hỏng trang
    log = OpLog(p)
    with pytest.raises(CorruptLog) as ei:
        log.load()
    assert ei.value.good_count == 0 and log.last_lsn == 0


def test_rewrite_lam_duoc_ca_khi_file_cu_hong(tmp_path):
    p = tmp_path / "n.db"
    good = make_entries(4)
    p.write_bytes(b"hong" * 100)
    log = OpLog(p)
    with pytest.raises(CorruptLog):
        log.load()
    log.rewrite(good[:3])
    log.close()
    again = OpLog(p)
    again.load()
    assert again.last_lsn == 3
    assert again.read_tables()[1] == {"SP01": 6}
    again.close()


def test_meta_luu_ben(tmp_path):
    p = tmp_path / "n.db"
    log = write_log(p, 1)
    log.set_meta("epoch", "2")
    log.rewrite(log.entries)                            # rewrite giữ meta
    log.close()
    again = OpLog(p)
    again.load()
    assert again.meta["epoch"] == "2"
    again.close()
