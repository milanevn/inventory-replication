import pytest

from dstock.domain import Inventory, Line, Voucher
from dstock.errors import InsufficientStock, InvalidVoucher


def v(kind, *lines, code="P1"):
    return Voucher(req_id="r", kind=kind, code=code, lines=[Line(s, q) for s, q in lines])


def test_nhap_xuat_cap_nhat_ton():
    inv = Inventory()
    inv.apply("NHAP", [Line("SP01", 10), Line("SP02", 5)])
    inv.validate(v("XUAT", ("SP01", 4)))
    inv.apply("XUAT", [Line("SP01", 4)])
    assert inv.snapshot() == {"SP01": 6, "SP02": 5}


def test_xuat_qua_ton_bi_tu_choi():
    inv = Inventory({"SP01": 3})
    with pytest.raises(InsufficientStock):
        inv.validate(v("XUAT", ("SP01", 4)))


def test_xuat_gop_dong_trung_ma():
    inv = Inventory({"SP01": 5})
    with pytest.raises(InsufficientStock):
        inv.validate(v("XUAT", ("SP01", 3), ("SP01", 3)))


@pytest.mark.parametrize("bad", [
    v("MUA", ("SP01", 1)),
    v("NHAP"),
    v("NHAP", ("SP01", 0)),
    v("NHAP", ("", 1)),
    v("NHAP", ("SP01", 1), code=" "),
])
def test_phieu_khong_hop_le(bad):
    with pytest.raises(InvalidVoucher):
        Inventory().validate(bad)


def test_digest_khong_phu_thuoc_thu_tu():
    a, b = Inventory(), Inventory()
    a.apply("NHAP", [Line("SP01", 1), Line("SP02", 2)])
    b.apply("NHAP", [Line("SP02", 2)])
    b.apply("NHAP", [Line("SP01", 1)])
    assert a.digest() == b.digest()
