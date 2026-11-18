import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import Cluster  # noqa: E402


# ---------------------------------------------------------------------------
# Test chấp nhận của các phần còn thiếu (tests/acceptance/):
#   pytestmark = pytest.mark.todo                         BẮT BUỘC (đủ đề) — chưa làm
#   @pytest.mark.todo(optional=True)                      TÙY CHỌN (làm nếu còn thời gian)
# Mặc định cả hai bị BỎ QUA (để main luôn xanh). Làm xong thì XÓA dấu todo của test đó.
#   pytest --run-todo          chạy thêm test BẮT BUỘC chưa làm (xem tiến độ)
#   pytest --run-optional      chạy thêm cả test TÙY CHỌN
#   pytest --run-todo -k triggers   chỉ test chấp nhận của triggers
# ---------------------------------------------------------------------------
def pytest_addoption(parser):
    parser.addoption("--run-todo", action="store_true", help="chạy cả test chấp nhận BẮT BUỘC chưa làm")
    parser.addoption("--run-optional", action="store_true", help="chạy cả test TÙY CHỌN")


def pytest_collection_modifyitems(config, items):
    run_todo = config.getoption("--run-todo") or config.getoption("--run-optional")
    run_opt = config.getoption("--run-optional")
    for item in items:
        m = item.get_closest_marker("todo")
        if not m:
            continue
        part = item.path.stem.removeprefix("test_")
        if m.kwargs.get("optional"):
            if not run_opt:
                item.add_marker(pytest.mark.skip(reason=f"TÙY CHỌN({part}) — chạy bằng --run-optional"))
        elif not run_todo:
            item.add_marker(pytest.mark.skip(reason=f"TODO({part}) — chạy bằng --run-todo"))


@pytest.fixture
def make_cluster(tmp_path):
    """Gọi make_cluster(links=..., snapshot_every=..., start=True) -> Cluster. Tự dọn sau test."""
    made: list[Cluster] = []

    def factory(links=None, snapshot_every: int = 50, start: bool = True) -> Cluster:
        c = Cluster(tmp_path, links=links, snapshot_every=snapshot_every)
        made.append(c)
        return c.start() if start else c

    yield factory
    for c in made:
        c.close()
