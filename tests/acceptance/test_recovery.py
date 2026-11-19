"""PHỤC HỒI khi dữ liệu bị tổn hại.

Quy tắc chọn nguồn (cluster.toml [recovery_sources]) — đi THEO CHIỀU CẠNH:
    N2, N3 <- N1;  N4 <- CHỈ N2;  N1 <- bản sao có last_lsn LỚN NHẤT.
Hỏi Status mọi nguồn trong danh sách, chọn nguồn OK có last_lsn lớn nhất (hòa: theo thứ tự).
Mọi nguồn chết thì giữ CORRUPT và THỬ LẠI sau (vòng nền suốt đời node).
Test chưa làm có dấu @pytest.mark.todo ngay trên nó. Làm xong việc nào thì xóa dấu của đúng
các test của việc đó (dấu optional=True chỉ xóa khi làm phần tùy chọn) và chạy chúng 3 lần liên tiếp đều xanh.
"""
import time

import pytest

from dstock import checkpoint
from dstock.oplog import OpLog
from harness import wait_until


def _ghi(c, n):
    for i in range(n):
        assert c.nhap(f"PN{i}", f"SP0{i % 3}:{i + 1}").ok
    assert c.wait_converged()


def _db_ok(c, nid):
    log = OpLog(c.db_path(nid))
    try:
        log.load()
        return True
    except Exception:
        return False
    finally:
        log.close()


@pytest.mark.todo
def test_ban_sao_sua_du_lieu_tu_phuc_hoi_khi_khoi_dong(make_cluster):
    c = make_cluster()
    _ghi(c, 6)
    c.stop("N3")
    c.corrupt_entry("N3", lsn=3)
    c.start("N3")
    assert wait_until(lambda: c.health("N3") == "OK", timeout=5)
    assert c.wait_converged(timeout=5)
    c.stop("N3")
    assert _db_ok(c, "N3")                   # CSDL trên đĩa hợp lệ trở lại


@pytest.mark.todo
def test_csdl_hong_duoc_cach_ly_khong_xoa(make_cluster):
    c = make_cluster()
    _ghi(c, 4)
    c.stop("N4")
    c.delete_entry("N4", lsn=2)
    c.start("N4")
    assert wait_until(lambda: c.health("N4") == "OK", timeout=5)
    quarantined = list(c.cfg.node_data_dir("N4").glob("dstock*.corrupt*"))
    assert quarantined, "phải giữ lại bản hỏng để điều tra"


@pytest.mark.todo
def test_file_csdl_hong_toi_muc_khong_mo_duoc(make_cluster):
    c = make_cluster()
    _ghi(c, 3)
    c.stop("N3")
    c.db_path("N3").write_bytes(b"rac" * 500)
    c.start("N3")
    assert wait_until(lambda: c.health("N3") == "OK", timeout=5)
    assert c.wait_converged(timeout=5)


@pytest.mark.todo
def test_ban_chinh_sua_du_lieu_phuc_hoi_tu_ban_sao(make_cluster):
    c = make_cluster()
    _ghi(c, 5)
    c.stop("N1")
    c.corrupt_entry("N1", lsn=2)
    c.start("N1")
    assert wait_until(lambda: c.health("N1") == "OK", timeout=5)
    assert c.lsn("N1") == 5
    assert c.nhap("PN-sau", "SP01:1").ok     # ghi tiếp được
    assert c.wait_converged()


@pytest.mark.todo
def test_ban_chinh_mat_duoi_phuc_hoi(make_cluster):
    c = make_cluster()
    _ghi(c, 5)
    c.stop("N1")
    c.truncate("N1", keep=2)
    c.start("N1")                            # Node phát hiện bản sao đi trước -> CORRUPT
    assert wait_until(lambda: c.health("N1") == "OK", timeout=5)
    assert c.lsn("N1") == 5
    assert c.nhap("PN-sau", "SP01:1").lsn == 6
    assert c.wait_converged()


@pytest.mark.todo
def test_ban_chinh_mat_ca_file_phuc_hoi(make_cluster):
    c = make_cluster()
    _ghi(c, 3)
    c.stop("N1")
    c.delete_db("N1")
    c.start("N1")
    assert wait_until(lambda: c.health("N1") == "OK", timeout=5)
    assert c.lsn("N1") == 3


@pytest.mark.todo
def test_N2_dang_tut_thi_N1_phuc_hoi_tu_node_moi_nhat(make_cluster):
    """1->2 không chờ xác nhận nên N2 có thể THIẾU dữ liệu; N3 mới hơn. N1 phải lấy từ N3."""
    c = make_cluster()
    _ghi(c, 2)
    c.stop("N2")
    for i in range(3):
        assert c.nhap(f"PX{i}", "SP01:1").ok
    assert c.wait_lsn("N3", 5)
    c.stop("N1")
    c.truncate("N1", keep=1)
    c.start("N2")                            # N2 lên lại ở lsn 2 (N1 chưa chạy nên chưa bắt kịp)
    c.start("N1")
    assert wait_until(lambda: c.health("N1") == "OK", timeout=5)
    assert c.lsn("N1") == 5                  # KHÔNG phải 2
    assert c.wait_converged(timeout=8)


@pytest.mark.todo
def test_N4_chi_phuc_hoi_tu_N2_va_thu_lai(make_cluster):
    """Đề: s4 chỉ nhận dữ liệu từ s2. N2 chết thì N4 CHỜ (giữ CORRUPT), không lấy từ N1."""
    c = make_cluster()
    _ghi(c, 3)
    c.stop("N4")
    c.stop("N2")
    c.corrupt_entry("N4", lsn=2)
    c.start("N4")                            # N1 vẫn sống nhưng KHÔNG phải nguồn của N4
    time.sleep(1.5)
    assert c.health("N4") == "CORRUPT"
    c.start("N2")
    assert wait_until(lambda: c.health("N4") == "OK", timeout=8)
    assert c.wait_converged(timeout=5)


# ---------------------------------------------------------------- TÙY CHỌN
@pytest.mark.todo(optional=True)
def test_ban_chinh_bi_phat_hien_hong_khi_dang_chay_tu_phuc_hoi(make_cluster):
    c = make_cluster()
    _ghi(c, 5)
    for nid in ("N1", "N2", "N3", "N4"):
        c.stop(nid)
    c.truncate("N1", keep=2)
    c.start("N1")                            # không hỏi được ai -> tạm OK
    c.start("N2")                            # kênh N1->N2 thấy N2 đi trước -> N1 CORRUPT -> phục hồi
    assert wait_until(lambda: c.health("N1") == "OK" and c.lsn("N1") == 5, timeout=8)


@pytest.mark.todo(optional=True)
def test_scrub_phat_hien_hong_khi_dang_chay(make_cluster):
    """Sửa CSDL khi node vẫn chạy -> được phát hiện và sửa lại (khắc phục tiến từ RAM).
    Scrub phải so sánh + ghi lại TRONG store.lock."""
    c = make_cluster()
    _ghi(c, 4)
    c.corrupt_entry("N4", lsn=1)
    assert not _db_ok(c, "N4")
    assert wait_until(lambda: _db_ok(c, "N4"), timeout=10)
    assert c.health("N4") == "OK"


@pytest.mark.todo(optional=True)
def test_checkpoint_dinh_ky_va_hop_le(make_cluster):
    c = make_cluster(snapshot_every=5)
    _ghi(c, 12)
    cp = checkpoint.load(c.cfg.node_data_dir("N2") / "checkpoint.json")
    assert cp is not None and cp.lsn >= 10
