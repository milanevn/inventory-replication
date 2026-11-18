"""Các lỗi dùng chung. `code` là mã trả qua gRPC (WriteReply.error / AppendReply.error)."""


class DStockError(Exception):
    code = "ERROR"


class InvalidVoucher(DStockError):
    code = "INVALID"


class InsufficientStock(DStockError):
    code = "INSUFFICIENT_STOCK"


class NotPrimary(DStockError):
    code = "NOT_PRIMARY"


class NodeCorrupt(DStockError):
    """Node phát hiện dữ liệu của mình bị tổn hại — từ chối ghi cho tới khi phục hồi."""
    code = "NODE_CORRUPT"


class CorruptLog(DStockError):
    """Oplog trên đĩa không hợp lệ. `bad_lsn` = lsn đầu tiên hỏng (các entry trước đó vẫn tốt)."""
    code = "CORRUPT_LOG"

    def __init__(self, msg: str, bad_lsn: int, good_count: int):
        super().__init__(msg)
        self.bad_lsn = bad_lsn
        self.good_count = good_count


class HashMismatch(DStockError):
    code = "HASH_MISMATCH"


class NoQuorum(DStockError):
    """Bản chính không thấy đa số thành viên — từ chối ghi để tránh hai bản chính."""
    code = "NO_QUORUM"


class PromoteRefused(DStockError):
    """Từ chối nâng bản chính (node bị loại còn sống / có node mới hơn / node đang hỏng)."""
    code = "PROMOTE_REFUSED"


class StaleRead(DStockError):
    """Chỉ còn node CŨ HƠN dữ liệu client đã thấy — trả về sẽ vi phạm nhất quán đọc đều."""
    code = "STALE_READ"
