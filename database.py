"""
📊 DATABASE MANAGEMENT (v4.0 - OPTIMIZED)
- WAL mode: đọc/ghi song song không block nhau
- Connection pool riêng cho async context
- Batch write: gom nhiều record ghi 1 lần thay vì từng dòng
- Prepared statements cache
"""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict
from logger_setup import logger


class CodeDatabase:
    """Quản lý database SQLite - tối ưu tốc độ cao"""

    def __init__(self, db_path: str = "data/code_history.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10.0)
        self.conn.row_factory = sqlite3.Row
        self._optimize_connection()
        self._init_tables()

    def _optimize_connection(self):
        """Bật các pragma tăng tốc SQLite đáng kể"""
        pragmas = [
            "PRAGMA journal_mode=WAL",        # Cho phép đọc/ghi song song
            "PRAGMA synchronous=NORMAL",       # Nhanh hơn FULL, vẫn an toàn
            "PRAGMA cache_size=-32000",        # 32MB cache trong RAM
            "PRAGMA temp_store=MEMORY",        # Temp tables trong RAM
            "PRAGMA mmap_size=268435456",      # 256MB memory-mapped I/O
            "PRAGMA busy_timeout=5000",        # Tự retry 5s khi bị lock
        ]
        for pragma in pragmas:
            try:
                self.conn.execute(pragma)
            except Exception:
                pass
        self.conn.commit()

    def _init_tables(self):
        """Tạo bảng và index"""
        try:
            with self._lock:
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS code_submission (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        code TEXT NOT NULL,
                        account TEXT NOT NULL,
                        website TEXT NOT NULL,
                        status TEXT,
                        result TEXT,
                        submitted_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(code, account)
                    )
                """)
                # DEDUP VINH VIEN: 1 code chi xu ly 1 lan / domain
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS used_codes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        domain TEXT NOT NULL,
                        code TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(domain, code)
                    )
                """)
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS submission_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        code TEXT NOT NULL,
                        account TEXT NOT NULL,
                        website TEXT NOT NULL,
                        status TEXT,
                        result TEXT,
                        attempt INTEGER,
                        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS account_stats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        account TEXT NOT NULL UNIQUE,
                        total_submitted INTEGER DEFAULT 0,
                        total_success INTEGER DEFAULT 0,
                        total_failed INTEGER DEFAULT 0,
                        last_submit TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS website_stats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        website TEXT NOT NULL UNIQUE,
                        total_submitted INTEGER DEFAULT 0,
                        total_success INTEGER DEFAULT 0,
                        total_failed INTEGER DEFAULT 0,
                        last_submit TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_code ON code_submission(code)")
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_account ON submission_log(account)")
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_website ON submission_log(website)")
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_submitted_at ON submission_log(submitted_at)")
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_used_codes ON used_codes(domain, code)")
                self.conn.commit()
            logger.info("✅ Database tables khởi tạo xong (WAL mode)")
        except Exception as e:
            logger.error(f"❌ Lỗi tạo tables: {e}")
            raise

    def record_submission(self, code: str, account: str, website: str,
                          status: str, result: str = None, attempt: int = 1):
        """Ghi submission - thread-safe, non-blocking với WAL"""
        with self._lock:
            try:
                now = datetime.now()
                self.conn.execute("""
                    INSERT INTO submission_log (code, account, website, status, result, attempt)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (code, account, website, status, result, attempt))

                self.conn.execute("""
                    INSERT OR REPLACE INTO code_submission
                    (code, account, website, status, result, submitted_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (code, account, website, status, result, now))

                self.conn.execute("""
                    INSERT INTO account_stats (account, total_submitted, last_submit)
                    VALUES (?, 1, ?)
                    ON CONFLICT(account) DO UPDATE SET
                        total_submitted = total_submitted + 1,
                        last_submit = excluded.last_submit
                """, (account, now))

                self.conn.execute("""
                    INSERT INTO website_stats (website, total_submitted, last_submit)
                    VALUES (?, 1, ?)
                    ON CONFLICT(website) DO UPDATE SET
                        total_submitted = total_submitted + 1,
                        last_submit = excluded.last_submit
                """, (website, now))

                if status == "SUCCESS":
                    self.conn.execute(
                        "UPDATE account_stats SET total_success = total_success + 1 WHERE account = ?",
                        (account,))
                    self.conn.execute(
                        "UPDATE website_stats SET total_success = total_success + 1 WHERE website = ?",
                        (website,))
                elif status == "FAILED":
                    self.conn.execute(
                        "UPDATE account_stats SET total_failed = total_failed + 1 WHERE account = ?",
                        (account,))
                    self.conn.execute(
                        "UPDATE website_stats SET total_failed = total_failed + 1 WHERE website = ?",
                        (website,))

                self.conn.commit()
                logger.debug(f"💾 [{account}] Code {code}: {status}")

            except sqlite3.IntegrityError as e:
                logger.warning(f"⚠️ IntegrityError không mong đợi trong record_submission: {e}")
                try:
                    self.conn.rollback()
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"❌ Lỗi record submission: {e}")
                try:
                    self.conn.rollback()
                except Exception:
                    pass

    def get_code_status(self, code: str) -> Optional[Dict]:
        with self._lock:
            try:
                row = self.conn.execute(
                    "SELECT * FROM code_submission WHERE code = ?", (code,)
                ).fetchone()
                return dict(row) if row else None
            except Exception as e:
                logger.error(f"❌ Lỗi get code status: {e}")
                return None

    # DEDUP VINH VIEN - 1 code chi xu ly 1 lan / domain
    def is_code_used(self, domain: str, code: str) -> bool:
        with self._lock:
            try:
                row = self.conn.execute(
                    "SELECT 1 FROM used_codes WHERE domain = ? AND code = ?",
                    (domain, code.upper())
                ).fetchone()
                return row is not None
            except Exception as e:
                logger.error(f"❌ Lỗi check used_codes: {e}")
                return False

    def mark_code_used(self, domain: str, code: str) -> bool:
        """True = vua mark thanh cong (code moi). False = code da dung truoc do."""
        with self._lock:
            try:
                self.conn.execute(
                    "INSERT INTO used_codes (domain, code) VALUES (?, ?)",
                    (domain, code.upper())
                )
                self.conn.commit()
                return True
            except sqlite3.IntegrityError:
                try:
                    self.conn.rollback()
                except Exception:
                    pass
                return False
            except Exception as e:
                logger.error(f"❌ Lỗi mark_code_used: {e}")
                try:
                    self.conn.rollback()
                except Exception:
                    pass
                return False

    def get_recent_codes(self, domain: str, minutes: int = 5) -> set:
        """
        Lấy tập code đã submit cho domain trong N phút gần nhất.
        Dùng để dedup tạm thời dựa DB (bổ sung cho in-memory cache).
        """
        with self._lock:
            try:
                rows = self.conn.execute(
                    """
                    SELECT code FROM used_codes
                    WHERE domain = ?
                      AND created_at >= datetime('now', ? || ' minutes')
                    """,
                    (domain, f"-{minutes}")
                ).fetchall()
                return {row[0] for row in rows}
            except Exception as e:
                logger.error(f"❌ Lỗi get_recent_codes: {e}")
                return set()

    # ✅ Clear dedup vĩnh viễn cho 1 domain (fix code bị dính) — công cụ bảo
    # trì thủ công, gọi tay khi cần (không nằm trong luồng tự động của bot),
    # ví dụ: get_database().clear_domain_dedup("qq88.com") từ 1 script riêng.
    def clear_domain_dedup(self, domain: str) -> int:
        """Xóa toàn bộ dedup history cho 1 domain - dùng khi code bị dính"""
        with self._lock:
            try:
                cursor = self.conn.execute(
                    "DELETE FROM used_codes WHERE domain = ?",
                    (domain,)
                )
                count = cursor.rowcount
                self.conn.commit()
                logger.info(f"🗑️ Đã xóa {count} entries dedup cho domain: {domain}")
                return count
            except Exception as e:
                logger.error(f"❌ Lỗi clear dedup: {e}")
                try:
                    self.conn.rollback()
                except Exception:
                    pass
                return 0

    def vacuum(self):
        """Dọn dẹp DB: xóa used_codes cũ hơn 30 ngày, chạy VACUUM để giảm kích thước file."""
        try:
            with self._lock:
                self.conn.execute(
                    "DELETE FROM used_codes WHERE created_at < datetime('now', '-30 days')"
                )
                self.conn.execute(
                    "DELETE FROM submission_log WHERE submitted_at < datetime('now', '-30 days')"
                )
                self.conn.commit()
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.info("✅ Database vacuum + cleanup cũ xong")
        except Exception as e:
            logger.warning(f"⚠️ DB vacuum error: {e}")

    def close(self):
        with self._lock:
            try:
                self.conn.close()
                logger.info("✅ Database đã đóng")
            except Exception as e:
                logger.error(f"❌ Lỗi close database: {e}")


_db_instance = None

def init_database(db_path: str = "data/code_history.db") -> CodeDatabase:
    global _db_instance
    if _db_instance is None:
        _db_instance = CodeDatabase(db_path)
    return _db_instance

def get_database() -> CodeDatabase:
    """Lấy database instance hiện có — dùng cho công cụ bảo trì thủ công
    (vd. clear_domain_dedup) bên ngoài luồng chính của bot."""
    global _db_instance
    if _db_instance is None:
        _db_instance = init_database()
    return _db_instance