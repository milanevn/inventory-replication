"""Toàn vẹn chuỗi giữa các node — bản chính KHÔNG BAO GIỜ được cấp lại một LSN mà bản sao đã có.

Chuỗi hash phát hiện được file bị SỬA giữa chừng, nhưng MẤT ĐUÔI hay MẤT CẢ FILE thì phần còn lại
vẫn là một chuỗi hợp lệ. Vì vậy cần so ĐẦU CHUỖI với node khác (Node._primary_startup_check và
ReplicationLink._check_head).

Các test ở đây kiểm BẤT BIẾN, đúng cả trước và sau khi có phục hồi:
    - hoặc N1 còn CORRUPT và TỪ CHỐI ghi,
    - hoặc N1 đã phục hồi đủ (lsn = 5) và lần ghi tiếp theo được lsn 6, khớp với mọi bản sao.
"""
from harness import wait_until


def _ghi(c, n):
    for i in range(n):
        assert c.nhap(f"PN{i}", "SP01:10").ok
    assert c.wait_converged()


def _khong_cap_lai_lsn(c, lsn_truoc: int) -> None:
    hash_n2 = [e.hash for e in c.nodes["N2"].store.oplog.entries]
    r = c.xuat("PX-sau", "SP01:1")
    if r.ok:                                                   # đã phục hồi
        assert r.lsn == lsn_truoc + 1
        assert c.wait_converged()
    else:
        assert r.error.startswith("NODE_CORRUPT")
        assert c.health("N1") == "CORRUPT"
    # các entry bản sao đã có KHÔNG bị thay
    assert [e.hash for e in c.nodes["N2"].store.oplog.entries][:len(hash_n2)] == hash_n2


def test_N1_mat_duoi_oplog_khong_cap_lai_lsn(make_cluster):
    c = make_cluster()
    _ghi(c, 5)
    c.stop("N1")
    c.truncate("N1", keep=3)
    c.start("N1")
    _khong_cap_lai_lsn(c, 5)


def test_N1_mat_ca_file_khong_cap_lai_lsn(make_cluster):
    c = make_cluster()
    _ghi(c, 3)
    c.stop("N1")
    c.delete_db("N1")
    c.start("N1")
    _khong_cap_lai_lsn(c, 3)


def test_N1_mat_duoi_khi_ban_sao_dang_tat_van_bi_phat_hien_sau(make_cluster):
    c = make_cluster()
    _ghi(c, 5)
    for nid in ("N1", "N2", "N3", "N4"):
        c.stop(nid)
    c.truncate("N1", keep=2)
    c.start("N1")                                             # không hỏi được ai -> tạm OK, lsn 2
    assert c.lsn("N1") == 2
    c.start("N2")
    # kênh N1->N2 thấy N2 đi trước: N1 bị đánh dấu CORRUPT (rồi recovery.py phục hồi về lsn 5)
    assert wait_until(lambda: c.health("N1") == "CORRUPT" or c.lsn("N1") == 5, timeout=3)


def test_GetStock_bao_health(make_cluster):
    c = make_cluster()
    _ghi(c, 2)
    c.stop("N1")
    c.truncate("N1", keep=1)
    c.start("N1")
    r = c.client.stock("N1")
    assert (r.health, r.lsn) in (("CORRUPT", 1), ("OK", 2))
