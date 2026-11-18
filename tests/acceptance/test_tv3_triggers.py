"""TV3 — Kích hoạt INTERVAL (N1→N3 sau n giây) và COUNT (N2→N4 sau n lần), đổi n lúc chạy.  Mốc M2.

Ngữ nghĩa đã chốt: interval = mỗi cập nhật tới N3 khoảng n giây sau khi ghi ở N1 (tính từ entry
chờ CŨ NHẤT), không phải "n giây kể từ lần gửi trước". Xem dstock/replication/triggers.py.
Xong phần của mình: XÓA dòng pytestmark bên dưới.
"""
import time

import pytest

from dstock.replication.triggers import CountTrigger, IntervalTrigger
from harness import SPEC_LINKS

pytestmark = pytest.mark.todo("TV3")


# ---------------------------------------------------------------- unit (không cần mạng)
def test_count_trigger():
    t = CountTrigger(3)
    assert not t.due(2, 99, 99)
    assert t.due(3, 0, 0)
    t.set_param(2)
    assert t.due(2, 0, 0)


def test_interval_trigger_tinh_tu_entry_cho_cu_nhat():
    t = IntervalTrigger(2)
    assert not t.due(5, 99, 1.0)           # rảnh lâu (since_last_flush lớn) nhưng entry mới chờ 1s
    assert t.due(5, 0.5, 2.01)


# ---------------------------------------------------------------- tích hợp
def test_N4_chi_nhan_khi_N2_du_n_lan(make_cluster):
    c = make_cluster(links=SPEC_LINKS)     # count n = 3
    c.nhap("P1", "SP01:1")
    c.nhap("P2", "SP01:1")
    assert c.wait_lsn("N2", 2)
    time.sleep(0.6)
    assert c.lsn("N4") == 0                # mới 2 lần -> chưa gửi
    c.nhap("P3", "SP01:1")
    assert c.wait_lsn("N4", 3, timeout=1.5)
    c.nhap("P4", "SP01:1")
    time.sleep(0.6)
    assert c.lsn("N4") == 3                # lần thứ 4 phải chờ thêm 2 lần nữa


def test_giam_n_luc_dang_don_thi_gui_ngay(make_cluster):
    c = make_cluster(links=SPEC_LINKS)
    for i in range(2):
        c.nhap(f"P{i}", "SP01:1")
    assert c.wait_lsn("N2", 2)
    time.sleep(0.3)
    assert c.lsn("N4") == 0
    c.client.set_link_param("N4", 2)
    assert c.wait_lsn("N4", 2, timeout=1.5)


def test_ranh_lau_roi_ghi_van_phai_cho_n_giay(make_cluster):
    """Lỗi kinh điển: cụm rảnh > n giây rồi ghi -> phiếu KHÔNG được tới N3 ngay."""
    c = make_cluster(links=SPEC_LINKS)     # interval n = 1s
    time.sleep(1.5)
    c.nhap("P1", "SP01:1")
    t0 = time.perf_counter()
    assert c.wait_lsn("N3", 1, timeout=2)
    assert 0.8 <= time.perf_counter() - t0 <= 1.6


@pytest.mark.todo("TV3", optional=True)
def test_N3_cap_nhat_theo_chu_ky_n_giay(make_cluster):
    """Ghi liên tục 3.5s; N3 chỉ thay đổi theo từng đợt cách nhau >= n giây, và bắt kịp trong ~n giây."""
    c = make_cluster(links=SPEC_LINKS)     # interval n = 1s
    changes, last = [], 0
    end = time.monotonic() + 3.5
    i = 0
    while time.monotonic() < end:
        if i % 5 == 0:
            c.nhap(f"P{i}", "SP01:1")
        i += 1
        lsn = c.lsn("N3")
        if lsn != last:
            changes.append(time.monotonic())
            last = lsn
        time.sleep(0.02)
    # Một lô được áp dụng từng entry một -> gộp các thay đổi sát nhau (< 0.3s) thành một ĐỢT.
    bursts = changes[:1] + [b for a, b in zip(changes, changes[1:]) if b - a > 0.3]
    gaps = [b - a for a, b in zip(bursts, bursts[1:])]
    assert len(bursts) >= 2
    assert all(g >= 0.8 for g in gaps), gaps
    assert c.wait_lsn("N3", c.lsn("N1"), timeout=1.5)


def test_doi_chu_ky_lon_xuong_nho(make_cluster):
    c = make_cluster(links=SPEC_LINKS)
    c.client.set_link_param("N3", 30)
    time.sleep(0.3)
    c.nhap("P1", "SP01:1")
    time.sleep(1.2)
    assert c.lsn("N3") == 0                # chu kỳ 30s -> chưa tới lượt
    c.client.set_link_param("N3", 0.5)     # entry đã chờ 1.2s > 0.5s -> gửi ngay
    assert c.wait_lsn("N3", 1, timeout=1.0)
