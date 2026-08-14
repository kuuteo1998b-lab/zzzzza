"""
Logger setup cho Bot v7.5 - CLEAN CONSOLE
- File: ghi TẤT CẢ từ DEBUG (rotate theo kích thước, giữ 5 file)
- Console: chỉ hiện những gì quan trọng, gọn đẹp
- DEBUG_VERBOSE_MODE=true → tắt filter console, hiện mọi thứ để debug
"""

import logging
import logging.handlers
import os
from dotenv import load_dotenv

load_dotenv()

# Khi bật DEBUG_VERBOSE_MODE=true trong .env, console filter bị tắt
# → hiện TẤT CẢ log (kể cả DEBUG) để dễ debug
DEBUG_VERBOSE_MODE = os.getenv("DEBUG_VERBOSE_MODE", "false").lower() == "true"


# ── Lọc bỏ log rác không cần thiết trên console ──────────────────────────
CONSOLE_SKIP_PHRASES = [
    "Error processing line",
    "Remainder of file ignored",
    "protobuf",
    "NoneType",
    "loader",
    "MESSAGE RAW",
    "text_len=",
    "Stealth JS loaded",
    "add_init_script",
    "Cannot setup route",
    "TabPool:",
    "tab riêng (persistent)",
    "Old msg",
    "OLD MSG",
    "Chat ",
    " not in config",
    "Cleanup done",
    "Cleanup error",
    "camoufox_minimize",
    "notify_admin",
    "history_writer",
    "Cannot write code history",
    "Cannot enqueue",
    "History queue",
    "⚠️ auto_solve error",
    "⚠️ Error finding input",
    "popup không mong muốn",
    "Đóng 0 popup",
    "close_camoufox error",
    "TASK CANCELLED",
    "[OLD MSG]",
    "⏭️ Chat",
    "⏭️ [OLD",
    "nspkg",
]

class CleanConsoleFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        for phrase in CONSOLE_SKIP_PHRASES:
            if phrase in msg:
                return False
        return True


class ColoredFormatter(logging.Formatter):
    COLORS = {
        'DEBUG':    '\033[36m',
        'INFO':     '\033[32m',
        'WARNING':  '\033[33m',
        'ERROR':    '\033[31m',
        'CRITICAL': '\033[35m',
    }
    RESET = '\033[0m'

    # Icon theo loại log
    ICONS = {
        'DEBUG':    '·',
        'INFO':     '✓',
        'WARNING':  '!',
        'ERROR':    '✗',
        'CRITICAL': '!!',
    }

    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.RESET)
        icon = self.ICONS.get(record.levelname, ' ')
        record = logging.makeLogRecord(record.__dict__)
        # Format gọn: [HH:MM:SS] ICON message
        record.levelname = f"{log_color}{icon}{self.RESET}"
        return super().format(record)


def setup_logger():
    os.makedirs("logs", exist_ok=True)

    logger = logging.getLogger("bot_logger")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # ── FILE HANDLER — rotate theo kích thước (LOG_ROTATION_MAX_BYTES) ───
    max_bytes    = int(os.getenv("LOG_ROTATION_MAX_BYTES",   str(10 * 1024 * 1024)))  # 10 MB
    backup_count = int(os.getenv("LOG_ROTATION_BACKUP_COUNT", "5"))

    file_handler = logging.handlers.RotatingFileHandler(
        os.getenv("LOG_FILE", "logs/bot_activity.log"),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%d/%m/%Y %H:%M:%S'
    ))

    # ── CONSOLE HANDLER ────────────────────────────────────────────────────
    console_level_name = os.getenv("CONSOLE_LOG_LEVEL", "INFO").upper()
    console_level = getattr(logging, console_level_name, logging.INFO)

    console_handler = logging.StreamHandler()

    if DEBUG_VERBOSE_MODE:
        # Verbose: tắt filter, hiện DEBUG+, dùng format đầy đủ hơn
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(logging.Formatter(
            '[%(asctime)s] [%(levelname)s] %(message)s',
            datefmt='%H:%M:%S'
        ))
        logger.warning("🔊 DEBUG_VERBOSE_MODE=true — console filter TẮT, hiện mọi log")
    else:
        console_handler.setLevel(console_level)
        console_handler.addFilter(CleanConsoleFilter())
        console_handler.setFormatter(ColoredFormatter(
            '[%(asctime)s] %(levelname)s %(message)s',
            datefmt='%H:%M:%S'
        ))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger


logger = setup_logger()