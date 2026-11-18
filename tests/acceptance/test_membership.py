"""PING định kỳ, luật đa số, nhận lại node quay về, heartbeat của kênh.

File được sửa: dstock/membership.py, các chỗ TODO trong dstock/replication/link.py.
Làm xong thì xóa dòng pytestmark (và dấu todo tùy chọn nếu làm) rồi chạy file này 3 lần liên tiếp đều xanh.
"""
import json
import time

import pytest

from harness import wait_until

pytestmark = pytest.mark.todo


def test_mat_mot_node_van_ghi_mat_hai_node_thi_tu_choi(make_cluster):
    c = make_cluster()
    assert c.nhap("PN1", "SP01:5").ok
    c.stop("N2")
    assert c.nhap("PN2", "SP01:1").ok                  # còn N1,N3,N4 = 3/4 >= 3
    c.stop("N3")                                      # còn N1,N4 = 2/4 < 3
    assert wait_until(lambda: not c.client.status("N1").has_quorum, timeout=4)
    r = c.nhap("PN3", "SP01:1")
    assert not r.ok and r.error.startswith("NO_QUORUM")
    assert c.lsn("N1") == 2                           # không cấp LSN nào khi thiếu đa số


def test_co_lai_da_so_thi_ghi_tiep(make_cluster):
    c = make_cluster()
    c.stop("N2")
    c.stop("N3")
    assert wait_until(lambda: not c.client.status("N1").has_quorum, timeout=4)
    c.start("N3")
    assert wait_until(lambda: c.client.status("N1").has_quorum, timeout=4)
    assert c.nhap("PN1", "SP01:1").ok


def test_da_so_tinh_theo_danh_sach_thanh_vien_hien_tai(make_cluster):
    """Sau khi nâng bản chính, thành viên có thể chỉ còn 2 -> đa số = 2. Mô phỏng bằng meta."""
    c = make_cluster()
    c.nodes["N1"].store.set_meta("members", json.dumps(["N1", "N2"]))
    assert c.nhap("PN1", "SP01:1").ok                  # thấy N2 -> 2/2
    c.stop("N2")
    assert wait_until(lambda: not c.client.status("N1").has_quorum, timeout=4)
    assert c.nhap("PN2", "SP01:1").error.startswith("NO_QUORUM")


def _gia_lap_nang(c, nid, members, epoch=1):
    """Dựng trạng thái "đã nâng nid lên bản chính" bằng meta, để test này không phải chờ failover.py."""
    node = c.nodes[nid]
    with node.role_lock:
        node.store.set_meta("epoch", str(epoch))
        node.store.set_meta("primary", nid)
        node.store.set_meta("members", json.dumps(members))
        node.apply_role()


def test_node_bi_loai_quay_lai_duoc_nhan_lai_vao_cum(make_cluster):
    """N1, N2 chết, N3 được nâng với thành viên [N3, N4]. N2 sống lại thì N3 phải nhận N2 vào cụm
    lại và đẩy dữ liệu cho nó (PING phải gửi cả tới node ngoài danh sách thành viên)."""
    c = make_cluster()
    for i in range(2):
        assert c.nhap(f"PN{i}", "SP01:1").ok
    assert c.wait_converged()
    c.stop("N1")
    c.stop("N2")
    _gia_lap_nang(c, "N3", ["N3", "N4"])
    assert wait_until(lambda: c.client.status("N3").has_quorum, timeout=4)
    assert c.nhap("PN-moi", "SP01:1").ok
    c.start("N2")
    assert wait_until(lambda: "N2" in c.client.status("N3").members, timeout=5)
    assert c.wait_lsn("N2", 3, timeout=5)


def test_heartbeat_phat_hien_dich_sap_khi_khong_co_ghi(make_cluster):
    c = make_cluster()
    c.nhap("PN1", "SP01:1")
    assert c.wait_converged()
    c.stop("N3")
    assert wait_until(lambda: c.link("N1", "N3").state == "DOWN", timeout=3)


def test_heartbeat_phat_hien_dich_mat_du_lieu(make_cluster):
    """N3 lên lại bị mất đuôi dữ liệu (còn 1/3 entry) mà KHÔNG có ghi mới: kênh không được tiếp tục
    tin acked_lsn=3 cũ — heartbeat phải thấy N3 tụt và gửi bù."""
    c = make_cluster()
    for i in range(3):
        c.nhap(f"PN{i}", "SP01:1")
    assert c.wait_converged()
    c.stop("N3")
    c.truncate("N3", keep=1)
    c.start("N3")
    assert c.wait_lsn("N3", 3, timeout=3)


@pytest.mark.todo(optional=True)
def test_backoff_khi_dich_chet_lau(make_cluster):
    """Đích chết, có dữ liệu chờ: số lần gọi trong 6 giây phải ít (backoff 0.5 -> 1 -> 2 -> ... 5s)."""
    c = make_cluster()
    c.stop("N3")
    link = c.link("N1", "N3")
    calls = {"n": 0}
    real = link.stub.Append

    def counting(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    link.stub.Append = counting
    c.nhap("PN1", "SP01:1")
    time.sleep(6)
    assert 2 <= calls["n"] <= 6, calls["n"]
