"""TV1: nâng bản chính thủ công và epoch (docs/operations.md, mục "Khi node chết"). Mốc M4.

File được sửa: dstock/failover.py, đoạn TODO(TV1) trong services.ReplicationService.Append (STALE_EPOCH).
Làm xong thì xóa dòng pytestmark bên dưới và chạy file này 3 lần liên tiếp đều xanh.
"""
import json

import grpc
import pytest

from dstock.client import DStockClient
from dstock.domain import Line
from dstock.rpc import dstock_pb2 as pb
from harness import wait_until

pytestmark = pytest.mark.todo("TV1")


def _role(c, nid):
    """Vai trò của nid, None nếu tạm chưa gọi được (kênh gRPC đang kết nối lại sau khi node khởi động lại)."""
    try:
        return c.client.status(nid, timeout=1).role
    except grpc.RpcError:
        return None


def _nang(c, nid, exclude):
    """Nâng nid lên bản chính, rồi đợi nó thấy đủ đa số. Ngay sau khi nâng, PING có thể chưa kịp
    ghi nhận các node còn sống (nhất là khi máy đang tải nặng), ghi ngay sẽ bị NO_QUORUM."""
    st = c.client.promote(nid, exclude)
    assert wait_until(lambda: c.client.status(nid).has_quorum, timeout=4)
    return st


def _ghi(c, n, start=0):
    for i in range(start, start + n):
        assert c.nhap(f"PN{i}", "SP01:1").ok


def test_N1_N2_sap_nang_N3_len_ban_chinh(make_cluster):
    c = make_cluster()
    _ghi(c, 4)
    assert c.wait_converged()
    c.stop("N1")
    c.stop("N2")
    st = _nang(c, "N3", ["N1", "N2"])
    assert (st.role, st.epoch, list(st.members)) == ("PRIMARY", 1, ["N3", "N4"])
    r = c.nhap("PN-moi", "SP01:1")
    assert r.ok and r.lsn == 5
    assert c.wait_converged(ids=("N3", "N4"), timeout=3)   # bản chính mới đẩy ngay tới N4
    c.restart("N3")                                         # vai trò lưu bền trong meta
    assert wait_until(lambda: _role(c, "N3") == "PRIMARY", timeout=3)


def test_client_moi_tu_tim_ra_ban_chinh_moi(make_cluster):
    c = make_cluster()
    _ghi(c, 2)
    assert c.wait_converged()
    c.stop("N1")
    c.stop("N2")
    _nang(c, "N3", ["N1", "N2"])
    fresh = DStockClient(c.cfg, timeout=2)                  # vẫn tưởng bản chính là N1
    try:
        assert fresh.nhap("PN-x", [Line("SP01", 1)]).ok
        assert fresh.primary == "N3"
    finally:
        fresh.close()


def test_tu_choi_nang_khi_node_bi_loai_van_con_song(make_cluster):
    c = make_cluster()
    _ghi(c, 2)
    c.stop("N2")                                            # N1 VẪN sống
    with pytest.raises(grpc.RpcError) as ei:
        c.client.promote("N3", ["N1", "N2"])
    assert ei.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    assert c.client.status("N1").role == "PRIMARY" and c.client.status("N3").epoch == 0


def test_tu_choi_nang_node_khong_moi_nhat(make_cluster):
    c = make_cluster()
    c.client.set_link_param("N4", 50)                       # N4 nhận theo lô 50 phiếu -> tụt
    _ghi(c, 3)
    assert c.wait_lsn("N3", 3)
    c.stop("N1")
    c.stop("N2")
    with pytest.raises(grpc.RpcError) as ei:
        c.client.promote("N4", ["N1", "N2"])                # N3 mới hơn N4
    assert ei.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    assert _nang(c, "N3", ["N1", "N2"]).role == "PRIMARY"


def test_ban_sao_tu_choi_ban_chinh_cu_bang_epoch(make_cluster):
    c = make_cluster()
    _ghi(c, 2)
    assert c.wait_converged()
    c.stop("N1")
    c.stop("N2")
    _nang(c, "N3", ["N1", "N2"])
    assert c.nhap("PN-moi", "SP01:1").ok
    assert wait_until(lambda: c.nodes["N4"].store.epoch == 1, timeout=3)   # N4 đã biết nhiệm kỳ mới
    stale = pb.AppendRequest(from_node="N1", entries=[], epoch=0)           # bản chính CŨ gửi tới
    reply = c.nodes["N3"].replication_stub("N4").Append(stale, timeout=2)
    assert not reply.ok and reply.error == "STALE_EPOCH" and reply.epoch == 1


def test_ban_chinh_cu_quay_lai_tu_ha_cap_va_luu_entry_mo_coi(make_cluster):
    c = make_cluster()
    _ghi(c, 4)
    assert c.wait_converged()
    c.client.set_link_param("N3", 30)                       # N3 tụt (chu kỳ 30s)
    c.stop("N2")
    _ghi(c, 2, start=10)                                    # N1 có lsn 5,6 mà N3, N4 KHÔNG có
    c.stop("N1")
    _nang(c, "N3", ["N1", "N2"])
    assert c.nhap("PN-moi", "SP01:1").lsn == 5              # lsn 5 MỚI, khác lsn 5 cũ của N1
    c.start("N1")                                           # bản chính cũ quay lại
    assert wait_until(lambda: _role(c, "N1") == "REPLICA", timeout=5)
    orphans = list(c.cfg.node_data_dir("N1").glob("orphans-*.jsonl"))
    assert orphans, "phải lưu entry mồ côi để xem xét thủ công"
    lines = orphans[0].read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["code"] for x in lines] == ["PN10", "PN11"]
    assert wait_until(lambda: c.lsn("N1") == 5 and c.digest("N1") == c.digest("N3"), timeout=5)
    r = c.client.inventory("N1").Write(pb.Voucher(req_id="x", kind="NHAP", code="P-x",
                                                  lines=[pb.Line(sku="SP01", qty=1)]), timeout=2)
    assert not r.ok and r.error.startswith("NOT_PRIMARY") and r.primary_hint == "N3"


def test_N1_chet_mot_minh_nang_tay_N2(make_cluster):
    """N1 chết một mình (vẫn còn đa số 3/4): không tự bầu, nâng tay node mới nhất."""
    c = make_cluster()
    _ghi(c, 3)
    assert c.wait_converged()
    c.stop("N1")
    st = _nang(c, "N2", ["N1"])
    assert (st.role, st.epoch, list(st.members)) == ("PRIMARY", 1, ["N2", "N3", "N4"])
    assert c.nhap("PN-moi", "SP01:1").lsn == 4
    assert c.wait_converged(ids=("N2", "N3", "N4"), timeout=3)   # chế độ sự cố: N2 đẩy tới N3, N4


def test_N1_song_mat_2_ban_sao_thu_hep_thanh_vien(make_cluster):
    """N2 và N3 chết (mất đa số): bắt buộc ghi tiếp thì thu hẹp thành viên ngay trên N1.
    N2 bị loại nên N4 không còn nguồn theo sơ đồ đề -> N1 đẩy thẳng tới N4 (chế độ sự cố)."""
    c = make_cluster()
    _ghi(c, 2)
    assert c.wait_converged()
    c.stop("N2")
    c.stop("N3")
    st = _nang(c, "N1", ["N2", "N3"])
    assert (st.role, st.epoch, list(st.members)) == ("PRIMARY", 1, ["N1", "N4"])
    assert c.nhap("PN-moi", "SP01:1").ok
    assert c.wait_lsn("N4", 3, timeout=3)


def test_tu_choi_nang_khi_chi_con_1_node(make_cluster):
    c = make_cluster()
    _ghi(c, 1)
    assert c.wait_converged()
    for nid in ("N1", "N2", "N4"):
        c.stop(nid)
    with pytest.raises(grpc.RpcError) as ei:
        c.client.promote("N3", ["N1", "N2", "N4"])
    assert ei.value.code() == grpc.StatusCode.FAILED_PRECONDITION
