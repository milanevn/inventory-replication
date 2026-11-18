"""Chế độ CHỈ ĐỌC khi bản chính sập.

Đặc tả:
  - client.stock() không chỉ định node: gọi bản chính; gặp lỗi gRPC thì CHUYỂN NGAY (không chờ
    monitor) sang node còn sống có last_lsn LỚN NHẤT; hòa thì theo thứ tự recovery_sources[primary].
  - StockReply.node_id / lsn / last_apply_ts cho biết dữ liệu cũ tới đâu (GUI hiển thị).
  - Nhất quán ĐỌC ĐỀU: cùng một client không bao giờ thấy lsn NHỎ HƠN lần đọc trước.
Xong: XÓA dòng pytestmark bên dưới.
"""
import pytest

pytestmark = pytest.mark.todo


def test_N1_sap_thi_doc_tu_node_moi_nhat(make_cluster):
    c = make_cluster()
    for i in range(4):
        c.nhap(f"PN{i}", "SP01:1")
    assert c.wait_converged()
    c.stop("N1")
    r = c.client.stock()                    # không chỉ định node
    assert r.node_id == "N2" and r.lsn == 4  # cả 3 cùng lsn 4 -> hòa -> N2 đứng đầu danh sách


def test_N1_va_N2_sap_van_doc_duoc_tu_N3_N4(make_cluster):
    c = make_cluster()
    c.nhap("PN1", "SP01:1")
    assert c.wait_converged()
    c.stop("N1")
    c.stop("N2")
    r = c.client.stock()
    assert r.node_id == "N3" and r.lsn == 1


def test_uu_tien_node_moi_hon(make_cluster):
    c = make_cluster()
    c.nhap("PN1", "SP01:1")
    assert c.wait_converged()
    c.stop("N2")                            # N2 dừng ở lsn 1
    c.nhap("PN2", "SP01:1")
    assert c.wait_lsn("N3", 2)
    c.stop("N1")
    r = c.client.stock()
    assert r.node_id == "N3" and r.lsn == 2


def test_nhat_quan_doc_deu(make_cluster):
    """Client đã thấy lsn 2; nếu chỉ còn node CŨ HƠN (lsn 1) thì báo StaleRead, không trả dữ liệu cũ."""
    from dstock.errors import StaleRead
    c = make_cluster()
    c.nhap("PN1", "SP01:1")
    assert c.wait_converged()
    c.client.set_link_param("N3", 30)       # N3 tụt lại ở lsn 1
    c.nhap("PN2", "SP01:1")
    assert c.wait_lsn("N4", 2)
    assert c.client.stock().lsn == 2        # đọc ở N1: lsn 2
    c.stop("N1")
    c.stop("N2")
    c.stop("N4")
    with pytest.raises(StaleRead):
        c.client.stock()                    # chỉ còn N3 (lsn 1 < 2 đã thấy)
