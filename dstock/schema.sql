-- =============================================================================
-- Schema CSDL của MỖI node (SQLite, file data/<node>/dstock.db)
--
-- change_log  : NGUỒN SỰ THẬT. Nhật ký thay đổi theo thao tác nghiệp vụ, lsn tăng dần,
--               có chuỗi hash (prev_hash -> hash) để phát hiện dữ liệu bị tổn hại.
-- san_pham, phieu, phieu_ct, ton_kho : dữ liệu DẪN XUẤT — luôn được ghi CÙNG TRANSACTION với
--               change_log; khi khởi động được đối chiếu lại với nhật ký (lệch => dựng lại).
-- meta        : epoch (nhiệm kỳ), bản chính hiện tại, danh sách thành viên.
-- =============================================================================

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS change_log (
    lsn          INTEGER PRIMARY KEY,         -- số thứ tự do bản chính cấp, bắt đầu từ 1
    req_id       TEXT    NOT NULL,            -- khóa chống ghi trùng do client sinh
    kind         TEXT    NOT NULL,            -- SANPHAM | NHAP | XUAT
    code         TEXT    NOT NULL,            -- số phiếu (SANPHAM: mã hàng)
    lines        TEXT    NOT NULL,            -- JSON [[ma, so_luong], ...]
    note         TEXT    NOT NULL,
    product_name TEXT    NOT NULL,
    unit         TEXT    NOT NULL,
    epoch        INTEGER NOT NULL,            -- nhiệm kỳ của bản chính đã cấp entry
    ts           REAL    NOT NULL,            -- thời điểm ghi ở bản chính
    prev_hash    TEXT    NOT NULL,
    hash         TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS san_pham (
    ma  TEXT PRIMARY KEY,
    ten TEXT NOT NULL,
    dvt TEXT NOT NULL                          -- đơn vị tính
);

CREATE TABLE IF NOT EXISTS phieu (
    lsn      INTEGER PRIMARY KEY REFERENCES change_log(lsn),
    so_phieu TEXT NOT NULL UNIQUE,
    loai     TEXT NOT NULL,                    -- NHAP | XUAT
    req_id   TEXT NOT NULL,
    ghi_chu  TEXT NOT NULL,
    ts       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS phieu_ct (
    lsn INTEGER NOT NULL REFERENCES phieu(lsn),
    ma  TEXT    NOT NULL,
    sl  INTEGER NOT NULL CHECK (sl > 0)
);

CREATE TABLE IF NOT EXISTS ton_kho (
    ma TEXT PRIMARY KEY,
    sl INTEGER NOT NULL CHECK (sl >= 0)
);
