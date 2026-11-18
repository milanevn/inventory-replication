import sqlite3

import pytest

from dstock.domain import Line, Voucher
from dstock.errors import InsufficientStock, NodeCorrupt, NotPrimary
from dstock.store import NodeStore


def voucher(req, kind, *lines):
    return Voucher(req_id=req, kind=kind, code=req, lines=[Line(s, q) for s, q in lines])


@pytest.fixture
def primary(tmp_path):
    s = NodeStore("N1", tmp_path / "N1", is_primary=True)
    s.open()
    yield s
    s.close()


@pytest.fixture
def replica(tmp_path):
    s = NodeStore("N2", tmp_path / "N2", is_primary=False)
    s.open()
    yield s
    s.close()


def sql(store, q, params=()):
    conn = sqlite3.connect(str(store.oplog.path), isolation_level=None)
    try:
        return conn.execute(q, params).fetchall()
    finally:
        conn.close()


def test_cap_lsn_tang_dan(primary):
    e1, _ = primary.write(voucher("a", "NHAP", ("SP01", 5)))
    e2, _ = primary.write(voucher("b", "XUAT", ("SP01", 2)))
    assert (e1.lsn, e2.lsn) == (1, 2)
    assert primary.stock() == {"SP01": 3}


def test_req_id_trung_khong_ghi_lai(primary):
    e1, dup1 = primary.write(voucher("a", "NHAP", ("SP01", 5)))
    e2, dup2 = primary.write(voucher("a", "NHAP", ("SP01", 5)))
    assert (dup1, dup2) == (False, True)
    assert e1.lsn == e2.lsn == 1
    assert primary.stock() == {"SP01": 5}


def test_xuat_qua_ton_khong_cap_lsn(primary):
    with pytest.raises(InsufficientStock):
        primary.write(voucher("a", "XUAT", ("SP01", 1)))
    assert primary.last_lsn == 0


def test_ban_sao_khong_nhan_ghi(replica):
    with pytest.raises(NotPrimary):
        replica.write(voucher("a", "NHAP", ("SP01", 1)))


def test_ban_sao_ap_dung_trung_lo_hong_sai_hash(primary, replica):
    for i in range(3):
        primary.write(voucher(f"r{i}", "NHAP", ("SP01", 1)))
    es = primary.oplog.entries

    r = replica.apply_replicated(es[:2])
    assert (r.last_lsn, r.last_hash, r.error) == (2, es[1].hash, "")
    assert replica.apply_replicated(es[:2]).error == ""          # gửi lại -> bỏ qua
    assert replica.stock() == {"SP01": 2}
    assert replica.apply_replicated([es[2]]).last_lsn == 3

    fresh = NodeStore("N3", primary.data_dir.parent / "N3", False)
    fresh.open()
    r = fresh.apply_replicated([es[1]])                          # thiếu lsn 1
    assert (r.last_lsn, r.last_hash, r.error) == (0, "", "GAP")
    assert fresh.apply_replicated([es[0]]).error == ""

    # entry lsn 2 của MỘT CHUỖI KHÁC (prev_hash không khớp) -> từ chối
    other = NodeStore("X", primary.data_dir.parent / "X", True)
    other.open()
    other.write(voucher("x1", "NHAP", ("SP09", 9)))
    foreign, _ = other.write(voucher("x2", "NHAP", ("SP09", 1)))
    assert fresh.apply_replicated([foreign]).error == "HASH_MISMATCH"


def test_entry_trung_lsn_khac_hash_la_phan_ky(primary, replica):
    from dataclasses import replace
    e, _ = primary.write(voucher("a", "NHAP", ("SP01", 1)))
    replica.apply_replicated([e])
    fake = replace(e, note="khác").sealed()
    r = replica.apply_replicated([fake])
    assert (r.last_lsn, r.error) == (1, "DIVERGED")
    assert replica.oplog.entries[0].hash == e.hash               # không bị ghi đè


def test_req_id_rong_bi_tu_choi(primary):
    from dstock.errors import InvalidVoucher
    with pytest.raises(InvalidVoucher):
        primary.write(voucher(" ", "NHAP", ("SP01", 1)))


def test_chuan_hoa_ma_hang_va_gioi_han_so_luong(primary):
    from dstock.errors import InvalidVoucher
    primary.write(voucher("a", "NHAP", (" sp01 ", 2)))
    primary.write(voucher("b", "NHAP", ("SP01", 3)))
    assert primary.stock() == {"SP01": 5}
    with pytest.raises(InvalidVoucher):
        primary.write(voucher("c", "NHAP", ("SP02", 2**63 - 1)))


def test_mo_lai_dung_lai_trang_thai(primary, tmp_path):
    primary.write(voucher("a", "NHAP", ("SP01", 5), ("SP02", 1)))
    primary.write(voucher("b", "XUAT", ("SP01", 2)))
    again = NodeStore("N1", tmp_path / "N1", True)
    again.open()
    assert again.inv.digest() == primary.inv.digest()
    assert again.req_index == primary.req_index


def test_oplog_hong_thi_tu_choi_ghi(primary, tmp_path):
    for i in range(3):
        primary.write(voucher(f"r{i}", "NHAP", ("SP01", 1)))
    sql(primary, "UPDATE change_log SET lines = '[[\"SP01\", 7]]' WHERE lsn = 1")
    again = NodeStore("N1", tmp_path / "N1", True)
    again.open()
    assert again.health == "CORRUPT"
    assert again.last_lsn == 0
    with pytest.raises(NodeCorrupt):
        again.write(voucher("z", "NHAP", ("SP01", 1)))


def test_bang_ton_bi_sua_tay_thi_dung_lai_tu_nhat_ky(primary, tmp_path):
    primary.write(voucher("a", "NHAP", ("SP01", 5)))
    sql(primary, "UPDATE ton_kho SET sl = 999 WHERE ma = 'SP01'")
    again = NodeStore("N1", tmp_path / "N1", True)
    again.open()
    assert again.health == "OK" and again.stock() == {"SP01": 5}      # nhật ký là nguồn sự thật
    assert again.oplog.read_tables()[1] == {"SP01": 5}                 # bảng đã được dựng lại
    again.close()


def test_khai_bao_san_pham_va_tu_tao_khi_nhap(primary):
    primary.write(Voucher(req_id="s1", kind="SANPHAM", code="sp01", lines=[],
                          product_name="Bút bi", unit="cây"))
    primary.write(voucher("a", "NHAP", ("SP01", 2), ("SP09", 1)))
    assert primary.inv.products == {"SP01": ("Bút bi", "cây"), "SP09": ("SP09", "")}
    assert primary.stock() == {"SP01": 2, "SP09": 1}


def test_khai_bao_san_pham_thieu_ten_bi_tu_choi(primary):
    from dstock.errors import InvalidVoucher
    with pytest.raises(InvalidVoucher):
        primary.write(Voucher(req_id="s1", kind="SANPHAM", code="SP01", lines=[]))


def test_so_phieu_khong_duoc_trung(primary):
    from dstock.errors import InvalidVoucher
    primary.write(Voucher(req_id="a", kind="NHAP", code="PN1", lines=[Line("SP01", 1)]))
    with pytest.raises(InvalidVoucher):
        primary.write(Voucher(req_id="b", kind="NHAP", code="PN1", lines=[Line("SP01", 1)]))
