"""Test chấp nhận mốc M0 — cụm 4 node chạy trọn luồng. Luôn phải XANH trên main."""
import threading

from harness import wait_until


def test_ghi_o_N1_lan_toi_ca_4_node(make_cluster):
    c = make_cluster()
    assert c.nhap("PN1", "SP01:10", "SP02:5").ok
    assert c.xuat("PX1", "SP01:4").ok
    assert c.wait_converged()
    for nid in ("N2", "N3", "N4"):
        assert c.nodes[nid].store.stock() == {"SP01": 6, "SP02": 5}


def test_xuat_qua_ton_bi_tu_choi_qua_grpc(make_cluster):
    c = make_cluster()
    c.nhap("PN1", "SP01:1")
    r = c.xuat("PX1", "SP01:2")
    assert not r.ok and r.error.startswith("INSUFFICIENT_STOCK")


def test_ban_sao_tu_choi_ghi(make_cluster):
    from dstock.rpc import dstock_pb2 as pb
    c = make_cluster()
    r = c.client.inventory("N2").Write(pb.Voucher(req_id="x", kind="NHAP", code="P",
                                                  lines=[pb.Line(sku="A", qty=1)]))
    assert not r.ok and r.error.startswith("NOT_PRIMARY")


def test_node_sap_roi_len_lai_tu_bat_kip(make_cluster):
    c = make_cluster()
    c.nhap("PN1", "SP01:10")
    assert c.wait_converged()
    c.stop("N3")
    for i in range(3):
        c.xuat(f"PX{i}", "SP01:1")
    c.start("N3")
    assert c.wait_converged(timeout=8)
    assert c.nodes["N3"].store.stock() == {"SP01": 7}


def test_hai_client_xuat_dong_thoi_khong_am_kho(make_cluster):
    c = make_cluster()
    c.nhap("PN1", "SP01:5")
    results = []

    def worker(i):
        results.append(c.xuat(f"PX{i}", "SP01:1").ok)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert results.count(True) == 5
    assert c.nodes["N1"].store.stock() == {"SP01": 0}
    assert c.wait_converged()


def test_doi_n_luc_dang_chay(make_cluster):
    c = make_cluster()
    info = c.client.set_link_param("N4", 7)
    assert (info.from_node, info.mode, info.param) == ("N2", "count", 7)
    st = c.client.status("N2")
    assert st.links[0].param == 7


def test_status_qua_admin(make_cluster):
    c = make_cluster()
    c.nhap("PN1", "SP01:3")
    assert wait_until(lambda: c.client.status("N1").links[0].acked_lsn == 1)
    st = c.client.status("N1")
    assert st.role == "PRIMARY" and st.health == "OK" and st.last_lsn == 1
    assert {l.to_node for l in st.links} == {"N2", "N3"}


def test_1_2_day_ngay_khong_cho_N2_xac_nhan(make_cluster):
    """Đề: 1->2 tức thời; quyết định: N1 KHÔNG chờ N2 xác nhận => N2 chết thì ghi vẫn nhanh."""
    import time
    c = make_cluster()
    c.nhap("PN1", "SP01:5")
    assert c.wait_lsn("N2", 1, timeout=1)          # bình thường N2 có gần như ngay
    c.stop("N2")
    t0 = time.perf_counter()
    assert c.nhap("PN2", "SP01:1").ok
    assert time.perf_counter() - t0 < 0.3
    c.start("N2")
    assert c.wait_converged(timeout=8)


def test_san_pham_lan_truyen_toi_moi_node(make_cluster):
    c = make_cluster()
    assert c.client.khai_bao("sp01", "Bút bi", "cây").ok
    assert c.nhap("PN1", "SP01:3", "SP02:1").ok
    assert c.wait_converged()
    for nid in ("N2", "N3", "N4"):
        assert c.nodes[nid].store.inv.products == {"SP01": ("Bút bi", "cây"), "SP02": ("SP02", "")}
    st = c.client.status("N4")
    assert st.products["SP01"] == "Bút bi|cây"


def test_status_bao_epoch_va_thanh_vien(make_cluster):
    c = make_cluster()
    st = c.client.status("N1")
    assert (st.epoch, st.primary_id, list(st.members)) == (0, "N1", ["N1", "N2", "N3", "N4"])
    assert st.has_quorum
    assert c.client.status("N3").primary_id == "N1"
