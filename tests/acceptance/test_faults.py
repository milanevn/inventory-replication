"""Lớp GÂY LỖI mạng (interceptor gRPC).

Mỗi lần interceptor thực sự gây lỗi (bỏ / cắt / trễ) phải gọi FaultInjector.count_injected() —
test dùng số này để chắc lỗi ĐÃ xảy ra (không thì test "vẫn hội tụ" qua được dù chưa làm gì).
Test chưa làm có dấu @pytest.mark.todo ngay trên nó. Làm xong việc nào thì xóa dấu của đúng
các test của việc đó (dấu optional=True chỉ xóa khi làm phần tùy chọn) và chạy chúng 3 lần liên tiếp đều xanh.
"""
import time

import pytest

from harness import wait_until


def _link_info(c, src, dst):
    return next(l for l in c.client.status(src).links if l.to_node == dst)


@pytest.mark.todo
def test_cat_kenh_N1_N3(make_cluster):
    c = make_cluster()
    c.client.set_fault("N1", "N3", partition=True)
    c.nhap("PN1", "SP01:1")
    time.sleep(1.5)
    assert c.lsn("N3") == 0
    assert c.lsn("N2") == 1                 # kênh khác không bị ảnh hưởng
    assert wait_until(lambda: c.link("N1", "N3").state == "DOWN", 3)
    assert _link_info(c, "N1", "N3").fault != ""
    assert c.nodes["N1"].faults.injected > 0

    c.client.set_fault("N1", "N3")          # gỡ lỗi
    assert c.wait_lsn("N3", 1, timeout=3)


@pytest.mark.todo(optional=True)
def test_bo_goi_100_phan_tram_tuong_duong_cat(make_cluster):
    c = make_cluster()
    c.client.set_fault("N2", "N4", drop_rate=1.0)
    for i in range(3):
        c.nhap(f"PN{i}", "SP01:1")
    time.sleep(1)
    assert c.lsn("N4") == 0
    assert c.nodes["N2"].faults.injected > 0


@pytest.mark.todo(optional=True)
def test_bo_goi_30_phan_tram_van_hoi_tu(make_cluster):
    c = make_cluster()
    c.client.set_fault("N1", "N3", drop_rate=0.3)
    n = 0
    # Ghi cho tới khi chắc chắn đã có lời gọi BỊ BỎ (ít lời gọi thì có thể không lần nào bị bỏ).
    while c.nodes["N1"].faults.injected < 3 and n < 60:
        n += 1
        c.nhap(f"PN{n}", "SP01:1")
        time.sleep(0.1)
    assert c.nodes["N1"].faults.injected >= 3
    assert c.wait_lsn("N3", n, timeout=20)


@pytest.mark.todo(optional=True)
def test_tre_mang(make_cluster):
    c = make_cluster()
    c.client.set_fault("N1", "N3", delay_ms=300)
    stub = c.nodes["N1"].replication_stub("N3")
    from dstock.rpc import dstock_pb2 as pb
    t0 = time.perf_counter()
    stub.Append(pb.AppendRequest(from_node="N1"), timeout=2)
    assert time.perf_counter() - t0 >= 0.28
    assert c.nodes["N1"].faults.injected > 0
