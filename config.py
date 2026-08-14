"""
⚙️ CẤU HÌNH BOT - 5 KÊNH: LLwin | XX88 | RR88 | GG88 | MM88
"""

import os
from dotenv import load_dotenv

load_dotenv()


def get_int_env(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None or str(value).strip() == "":
        return default
    try:
        return int(value)
    except Exception:
        return default


def get_float_env(key: str, default: float) -> float:
    value = os.getenv(key)
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(value)
    except Exception:
        return default


def get_bool_env(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in ("true", "1", "yes", "y", "on")


class Config:
    # ==========================================
    # 🔐 TELEGRAM
    # ==========================================
    # OCR backend (Tesseract local)
    TESSERACT_PATH = os.getenv("TESSERACT_PATH", "")

    CAPTCHA_SITES: list = [s.strip() for s in os.getenv(
        "CAPTCHA_SITES",
        "llwincode.com,xx88code.com,rr88code.com,gg88code.com,mm88code.com"
    ).split(",") if s.strip()]

    API_ID       = get_int_env("API_ID", 0)
    API_HASH     = os.getenv("API_HASH", "")
    SESSION_NAME = os.getenv("SESSION_NAME", "session_bot")

    # ==========================================
    # 📌 PROFILE TRÌNH DUYỆT CỐ ĐỊNH (Edge)
    # ==========================================
    BROWSER_PROFILE_BASE_DIR = os.getenv("BROWSER_PROFILE_BASE_DIR", "browser_profiles/bot_profile")

    # ==========================================
    # 🔄 POLLING FALLBACK
    # ==========================================
    POLLING_ENABLED          = get_bool_env("POLLING_ENABLED", True)
    POLLING_INTERVAL_SECONDS = get_int_env("POLLING_INTERVAL_SECONDS", 15)

    # ==========================================
    # 🕐 TIMEZONE
    # ==========================================
    TIMEZONE = "Asia/Ho_Chi_Minh"

    # ==========================================
    # 📝 LOG / DATABASE
    # ==========================================
    LOG_LEVEL    = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE     = os.getenv("LOG_FILE", "logs/bot_activity.log")
    LOG_FORMAT   = "%(asctime)s - %(levelname)s - %(message)s"
    MAX_LOG_SIZE = get_int_env("MAX_LOG_SIZE", 10485760)
    BACKUP_COUNT = get_int_env("BACKUP_COUNT", 5)
    CONSOLE_LOG  = True

    DATABASE_PATH = os.getenv("DATABASE_PATH", "data/code_history.db")
    HISTORY_FILE  = "logs/history_success.txt"

    # ==========================================
    # 🔎 CODE FILTER
    # ==========================================
    CODE_MIN_LENGTH = 6
    CODE_MAX_LENGTH = 15

    SPECIAL_CODE_CHARS_30 = r"""~!@#$%^&*()_+{}|:\"<>?`=[]\\;',./"""

    CODE_FILTER_GROUPS = {
        # ── Dùng chung cho XX88 / RR88 / GG88 / MM88 ──────────────────────
        "multi_site_strict": {
            "description": "Dùng chung cho XX88, RR88, GG88, MM88",
            "url_keywords": ["xx88", "rr88", "gg88", "mm88"],
            "allowed_sites": ["xx88", "rr88", "gg88", "mm88"],
            "allow_numeric": False,
            "allow_random_mix": False,
            "require_uppercase": True,
            "prefer_spoiler": True,
            "marker_scan_lines": 3,
            "allow_fallback": False,
            "special_chars_group": "SPECIAL_CODE_CHARS_30",
            "special_chars": SPECIAL_CODE_CHARS_30,
            "min_special_chars": 0,
            "min_entropy": 2.0,
            "uppercase_min_entropy": 2.5,
            "soft_blacklist": ["CODE", "GAME", "FREE", "VIP", "NAP", "RUT"],
        },
        # ── LLwin riêng ───────────────────────────────────────────────────
        "llwin": {
            "description": "Dùng riêng cho LLwin - code IN HOA",
            "url_keywords": ["llwin", "llw", "88llwin", "84888"],
            "allowed_sites": ["llwin"],
            "allow_numeric": False,
            "allow_random_mix": False,
            "require_uppercase": True,
            "prefer_spoiler": True,
            "marker_scan_lines": 4,
            "allow_fallback": False,
            "special_chars_group": "SPECIAL_CODE_CHARS_30",
            "special_chars": SPECIAL_CODE_CHARS_30,
            # ↓ Hạ xuống 1 để code dạng KT5_H (chỉ có gạch dưới) qua được
            #   validator trong spoiler. Dòng bẫy K6$OSX / R%UAZO được lọc
            #   trực tiếp trong extract_llwin_code12_lines().
            "min_special_chars": 1,
            "min_entropy": 2.0,
            "uppercase_min_entropy": 2.5,
            "soft_blacklist": ["CODE", "GAME", "FREE", "VIP", "NAP", "RUT"],
        },
        # ── Fallback ──────────────────────────────────────────────────────
        "default": {
            "description": "Fallback nếu URL chưa thuộc nhóm nào",
            "url_keywords": [],
            "allowed_sites": [],
            "allow_numeric": True,
            "allow_random_mix": True,
            "require_uppercase": False,
            "prefer_spoiler": True,
            "min_entropy": 2.3,
            "uppercase_min_entropy": 2.9,
            "soft_blacklist": ["CODE", "GAME", "FREE", "VIP", "NAP", "RUT"],
        },
    }

    # ==========================================
    # 🖥️ ACCOUNT GROUPS
    # ==========================================
    CDP_CONNECTIONS = {
        "main": [
            "kaoboy012",
            "kuuteo012",
            "dad131",
            "dad123",
            "conve99sau",
            "minichan",
            "kuuteo0123",
            "hugolan",
            "hugolan012",
        ]
    }

    # ==========================================
    # 🖥️ REAL BROWSER
    # ==========================================
    BROWSER_LOCALE     = os.getenv("BROWSER_LOCALE", "vi-VN")
    BROWSER_TIMEZONE   = os.getenv("BROWSER_TIMEZONE", "Asia/Ho_Chi_Minh")
    HEADLESS_MODE      = get_bool_env("HEADLESS_MODE", False)
    BROWSER_READY_WAIT = get_int_env("BROWSER_READY_WAIT", 5)

    # ==========================================
    # 📡 TELEGRAM CHANNEL CONFIG
    # ==========================================
    # 📌 CÁCH TÍNH chat_id cho Telethon:
    #    channel_id (từ Telegram client) → chat_id = -(channel_id + 1_000_000_000_000)
    #    Ví dụ: -3873843218 → -(3873843218 + 1_000_000_000_000) = -1003873843218
    #
    # 📌 has_video=True  → kênh đăng code qua video/OCR (chỉ 2 kênh này)
    # 📌 has_video=False → kênh text/spoiler thông thường (mặc định)
    # ==========================================
    CHANNEL_CONFIG = {

        # ══════════════════════════════════════════════════════════════════
        # 🟦 LLWIN — llwincode.com
        # Extraction: ưu tiên spoiler → CODE 1:/CODE 2: format
        # ══════════════════════════════════════════════════════════════════

        -1003859359508: {
            "name": "LLwin ĐỈNH CAO CHIẾN THẮNG",
            "url": "https://llwincode.com",
            "filter_group": "llwin",
            "priority": 1,
            "has_video": False,
            "accounts": [
                {"username": "kaoboy012",  "priority": 1},
                {"username": "conve99sau", "priority": 2},
            ],
        },
        -1003873843218: {
            # ⭐ Kênh này đăng code qua VIDEO — bật OCR
            "name": "LLwin PHÁT CODE MIỄN PHÍ",
            "url": "https://llwincode.com",
            "filter_group": "llwin",
            "priority": 2,
            "has_video": True,
            "accounts": [
                {"username": "kaoboy012",  "priority": 1},
                {"username": "conve99sau", "priority": 2},
            ],
        },
        -1003903971775: {
            "name": "LLwin GIẢI TRÍ 24H",
            "url": "https://llwincode.com",
            "filter_group": "llwin",
            "priority": 3,
            "has_video": False,
            "accounts": [
                {"username": "kaoboy012",  "priority": 1},
                {"username": "kuuteo012",  "priority": 2},
            ],
        },
        -1003506071961: {
            "name": "LLwin DỊCH VỤ GIAI NHÂN",
            "url": "https://llwincode.com",
            "filter_group": "llwin",
            "priority": 4,
            "has_video": False,
            "accounts": [
                {"username": "conve99sau", "priority": 1},
                {"username": "kuuteo012",  "priority": 2},
            ],
        },
        -1003791977466: {
            "name": "LLwin Đấu Trường MMA",
            "url": "https://llwincode.com",
            "filter_group": "llwin",
            "priority": 5,
            "has_video": False,
            "accounts": [
                {"username": "kaoboy012",  "priority": 1},
                {"username": "conve99sau", "priority": 2},
            ],
        },

        # ══════════════════════════════════════════════════════════════════
        # 🟥 XX88 — xx88code.com
        # ══════════════════════════════════════════════════════════════════

        -1002817093108: {
            # ⭐ Kênh này đăng code qua VIDEO — bật OCR
            "name": "PHÁT CODE XX88",
            "url": "https://xx88code.com/",
            "filter_group": "multi_site_strict",
            "priority": 10,
            "has_video": True,
            "accounts": [
                {"username": "dad131",  "priority": 1},
                {"username": "hugolan", "priority": 2},
            ],
        },
        -1003734537786: {
            "name": "XX88 SĂN CODE MỖI NGÀY",
            "url": "https://xx88code.com/",
            "filter_group": "multi_site_strict",
            "priority": 11,
            "has_video": False,
            "accounts": [
                {"username": "dad131",  "priority": 1},
                {"username": "hugolan", "priority": 2},
            ],
        },
        -1002768264448: {
            "name": "XX88 THỂ THAO ESPORT",
            "url": "https://xx88code.com/",
            "filter_group": "multi_site_strict",
            "priority": 12,
            "has_video": False,
            "accounts": [
                {"username": "hugolan",    "priority": 1},
                {"username": "hugolan012", "priority": 2},
            ],
        },
        -1002730903277: {
            "name": "XX88 DỊCH VỤ GIAI NHÂN",
            "url": "https://xx88code.com/",
            "filter_group": "multi_site_strict",
            "priority": 13,
            "has_video": False,
            "accounts": [
                {"username": "dad131",     "priority": 1},
                {"username": "hugolan012", "priority": 2},
            ],
        },

        # ══════════════════════════════════════════════════════════════════
        # 🟨 GG88 — gg88code.com
        # ══════════════════════════════════════════════════════════════════

        -1003731231345: {
            "name": "G88 DỊCH VỤ GIAI NHÂN",
            "url": "https://gg88code.com/",
            "filter_group": "multi_site_strict",
            "priority": 20,
            "has_video": False,
            "accounts": [
                {"username": "dad123",     "priority": 1},
                {"username": "hugolan012", "priority": 2},
            ],
        },
        -1003218299330: {
            "name": "GG88 Meme & Gif - VUI LÀ CHÍNH",
            "url": "https://gg88code.com/",
            "filter_group": "multi_site_strict",
            "priority": 21,
            "has_video": False,
            "accounts": [
                {"username": "dad123",     "priority": 1},
                {"username": "hugolan012", "priority": 2},
            ],
        },
        -1003282310886: {
            "name": "Săn Code GG88 Mỗi Ngày",
            "url": "https://gg88code.com/",
            "filter_group": "multi_site_strict",
            "priority": 22,
            "has_video": False,
            "accounts": [
                {"username": "hugolan012", "priority": 1},
                {"username": "dad123",     "priority": 2},
            ],
        },

        # ══════════════════════════════════════════════════════════════════
        # 🟩 MM88 — mm88code.com
        # ══════════════════════════════════════════════════════════════════

        -1003134541072: {
            "name": "MM88VIP Dịch Vụ Giai Nhân",
            "url": "https://mm88code.com",
            "filter_group": "multi_site_strict",
            "priority": 30,
            "has_video": False,
            "accounts": [
                {"username": "kaoboy012", "priority": 1},
                {"username": "dad131",    "priority": 2},
            ],
        },
        -1002957135848: {
            "name": "MM88 Cộng Đồng Săn Code",
            "url": "https://mm88code.com",
            "filter_group": "multi_site_strict",
            "priority": 31,
            "has_video": False,
            "accounts": [
                {"username": "kaoboy012",  "priority": 1},
                {"username": "kuuteo0123", "priority": 2},
            ],
        },
        -1002783916865: {
            "name": "MM88 Kênh Chính Thức",
            "url": "https://mm88code.com",
            "filter_group": "multi_site_strict",
            "priority": 32,
            "has_video": False,
            "accounts": [
                {"username": "dad131",    "priority": 1},
                {"username": "kaoboy012", "priority": 2},
            ],
        },
        -1000248590547: {
            "name": "MM88 Cộng Đồng Giao Lưu",
            "url": "https://mm88code.com",
            "filter_group": "multi_site_strict",
            "priority": 33,
            "has_video": False,
            "accounts": [
                {"username": "kuuteo0123", "priority": 1},
                {"username": "kaoboy012",  "priority": 2},
            ],
        },
        -1003049205648: {
            "name": "MM88 Dịch Vụ Gái Xinh",
            "url": "https://mm88code.com",
            "filter_group": "multi_site_strict",
            "priority": 34,
            "has_video": False,
            "accounts": [
                {"username": "kaoboy012", "priority": 1},
                {"username": "dad131",    "priority": 2},
            ],
        },
        -1002925260801: {
            "name": "TƯ LIỆU HÌNH ẢNH MM88",
            "url": "https://mm88code.com",
            "filter_group": "multi_site_strict",
            "priority": 35,
            "has_video": False,
            "accounts": [
                {"username": "dad131",    "priority": 1},
                {"username": "kaoboy012", "priority": 2},
            ],
        },
        -1002909602359: {
            "name": "CODE FREE MM88",
            "url": "https://mm88code.com",
            "filter_group": "multi_site_strict",
            "priority": 36,
            "has_video": False,
            "accounts": [
                {"username": "kaoboy012",  "priority": 1},
                {"username": "kuuteo0123", "priority": 2},
            ],
        },

        # ══════════════════════════════════════════════════════════════════
        # 🟪 RR88 — rr88code.com
        # ══════════════════════════════════════════════════════════════════

        -1002386905514: {
            "name": "RR88 DỊCH VỤ GIAI NHÂN",
            "url": "https://rr88code.com",
            "filter_group": "multi_site_strict",
            "priority": 40,
            "has_video": False,
            "accounts": [
                {"username": "kaoboy012", "priority": 1},
                {"username": "minichan",  "priority": 2},
            ],
        },
        -1003995542988: {
            "name": "RR88 MINIGAME HÀNG NGÀY",
            "url": "https://rr88code.com",
            "filter_group": "multi_site_strict",
            "priority": 41,
            "has_video": False,
            "accounts": [
                {"username": "minichan",  "priority": 1},
                {"username": "kaoboy012", "priority": 2},
            ],
        },
        -1000264256462: {
            "name": "RR88 PHÁT CODE NỔ HŨ - BẮN CÁ",
            "url": "https://rr88code.com",
            "filter_group": "multi_site_strict",
            "priority": 42,
            "has_video": False,
            "accounts": [
                {"username": "kaoboy012", "priority": 1},
                {"username": "minichan",  "priority": 2},
            ],
        },

        # ══════════════════════════════════════════════════════════════════
        # ❓ KHÔNG XÁC ĐỊNH SITE
        # ══════════════════════════════════════════════════════════════════

        # ⚠️  GÁI 18+: chưa rõ site — tạm để mm88code.com.
        #    Nếu sai, đổi "url" và "filter_group" cho đúng.
        -1003936595246: {
            "name": "GÁI 18+",
            "url": "https://mm88code.com",
            "filter_group": "multi_site_strict",
            "priority": 99,
            "has_video": False,
            "accounts": [
                {"username": "kaoboy012", "priority": 1},
                {"username": "dad131",    "priority": 2},
            ],
        },
    }

    # ==========================================
    # 🚫 BLACKLIST
    # ==========================================
    CODE_BLACKLIST = [
        "COM", "HTTP", "HTTPS", "WWW",
        "FACEBOOK", "TELEGRAM",
        "CHECK", "CLIP", "VUI", "BOT",
        "DAILY", "TRUYCAP", "BANCA", "NOHU",
        "ONLINE", "FREE", "CODE", "GIFTCODE",
        "MINIGAME", "GAME", "THETHAO",
        "O8THETHAO", "BONGDA", "TROLL",
    ]

    # ==========================================
    # ⚙️ FEATURE FLAGS
    # ==========================================
    ENABLE_RETRY                    = True
    ENABLE_CIRCUIT_BREAKER          = True
    ENABLE_DATABASE_TRACKING        = True
    ENABLE_RATE_LIMITING            = True
    ENABLE_MONITORING               = True
    ENABLE_ADVANCED_ANTI_DETECTION  = True

    SKIP_BRING_TO_FRONT = get_bool_env("SKIP_BRING_TO_FRONT", False)
    MANUAL_CF_TIMEOUT   = get_int_env("MANUAL_CF_TIMEOUT", 600)

    TELEGRAM_ADMIN_ID = get_int_env("TELEGRAM_ADMIN_ID", 0)

    # ==========================================
    # 🛡️ CLOUDFLARE ANTI-DETECTION
    # ==========================================
    VIEWPORT_WIDTH  = get_int_env("VIEWPORT_WIDTH", 1440)
    VIEWPORT_HEIGHT = get_int_env("VIEWPORT_HEIGHT", 900)

    INPUT_TYPE_DELAY_MIN = get_int_env("INPUT_TYPE_DELAY_MIN", 20)
    INPUT_TYPE_DELAY_MAX = get_int_env("INPUT_TYPE_DELAY_MAX", 80)

    SUBMIT_CLICK_DELAY_MIN = get_float_env("SUBMIT_CLICK_DELAY_MIN", 0.3)
    SUBMIT_CLICK_DELAY_MAX = get_float_env("SUBMIT_CLICK_DELAY_MAX", 0.8)

    # ==========================================
    # ⏱️ TIMEOUT / SPEED
    # ==========================================
    PAGE_LOAD_TIMEOUT        = get_int_env("PAGE_LOAD_TIMEOUT", 30000)
    CLOUDFLARE_WAIT_TIMEOUT  = get_int_env("CLOUDFLARE_WAIT_TIMEOUT", 60000)
    CLOUDFLARE_CLICK_SLEEP   = get_float_env("CLOUDFLARE_CLICK_SLEEP", 1.5)

    SITE_CODE_DEDUP_TTL = get_float_env("SITE_CODE_DEDUP_TTL", 30.0)

    SUBMIT_TIMEOUT        = 5000
    RESULT_WAIT           = get_int_env("RESULT_WAIT", 1000)
    BROWSER_SPAWN_TIMEOUT = 15000

    MAX_CONCURRENT_SUBMITS            = get_int_env("MAX_CONCURRENT_TASKS", 3)
    MAX_CONCURRENT_SUBMITS_PER_DOMAIN = get_int_env("MAX_CONCURRENT_SUBMITS_PER_DOMAIN", 2)
    MAX_RETRY_FAILED_CODE             = 2
    MAX_RETRIES_PER_ACCOUNT           = get_int_env("MAX_RETRIES_PER_ACCOUNT", 2)
    RETRY_ON_TIMEOUT                  = get_bool_env("RETRY_ON_TIMEOUT", True)

    MIN_DELAY_BETWEEN_SUBMITS = get_float_env("MIN_DELAY_BETWEEN_SUBMITS", 0.5)

    REQUESTS_PER_MINUTE = get_int_env("REQUESTS_PER_MINUTE", 30)
    MAX_BURST           = get_int_env("MAX_BURST", 5)

    AUTO_SUBMIT_ENABLED     = get_bool_env("AUTO_SUBMIT_ENABLED", True)
    AUTO_SUBMIT_DELAY       = get_float_env("AUTO_SUBMIT_DELAY", 0.3)
    HUMAN_LIKE_TYPING_SPEED = get_float_env("HUMAN_LIKE_TYPING_SPEED", 0.05)
    RANDOM_DELAY_MIN        = get_float_env("RANDOM_DELAY_MIN", 0.1)
    RANDOM_DELAY_MAX        = get_float_env("RANDOM_DELAY_MAX", 0.5)

    INPUT_DETECTION_STRATEGY   = os.getenv("INPUT_DETECTION_STRATEGY", "advanced")
    INPUT_DETECTION_TIMEOUT    = get_int_env("INPUT_DETECTION_TIMEOUT", 5000)
    MULTIPLE_SELECTOR_ATTEMPTS = get_int_env("MULTIPLE_SELECTOR_ATTEMPTS", 4)

    RESULT_DETECTION_METHODS = get_int_env("RESULT_DETECTION_METHODS", 5)
    RESULT_DETECTION_TIMEOUT = get_int_env("RESULT_DETECTION_TIMEOUT", 5000)
    SCREENSHOT_ON_UNKNOWN    = get_bool_env("SCREENSHOT_ON_UNKNOWN", False)

    # ==========================================
    # ⚡ TELEGRAM REALTIME / QUEUE
    # ==========================================
    MESSAGE_QUEUE_MAXSIZE      = get_int_env("MESSAGE_QUEUE_MAXSIZE", 2000)
    MESSAGE_WORKERS            = get_int_env("MESSAGE_WORKERS", 4)
    MAX_CONCURRENT_PROCESSING  = get_int_env("MAX_CONCURRENT_PROCESSING", 24)

    HEARTBEAT_INTERVAL            = get_float_env("HEARTBEAT_INTERVAL", 300.0)
    TELEGRAM_CATCH_UP             = get_bool_env("TELEGRAM_CATCH_UP", False)
    BACKGROUND_MAINTENANCE_DELAY  = get_int_env("BACKGROUND_MAINTENANCE_DELAY", 300)

    # ==========================================
    # ⚙️ WATCHDOG / MISC
    # ==========================================
    TAB_FAIL_THRESHOLD           = get_int_env("TAB_FAIL_THRESHOLD", 5)
    PENDING_IMAGE_TTL            = get_float_env("PENDING_IMAGE_TTL", 180.0)
    INPUT_CACHE_CLEANUP_INTERVAL = get_float_env("INPUT_CACHE_CLEANUP_INTERVAL", 300.0)
    CDP_PING_INTERVAL            = get_float_env("CDP_PING_INTERVAL", 60.0)

    # ==========================================
    # 🆕 TAB POOL
    # ==========================================
    # Số tab dự phòng giữ sẵn. Tăng nếu nhiều kênh submit cùng lúc.
    TAB_POOL_SIZE = get_int_env("TAB_POOL_SIZE", 3)

    # ==========================================
    # 🆕 OCR
    # ==========================================
    # Ngưỡng tin cậy OCR (0.0–1.0). Kết quả dưới ngưỡng bị bỏ qua.
    OCR_CONFIDENCE_THRESHOLD = get_float_env("OCR_CONFIDENCE_THRESHOLD", 0.70)

    # ==========================================
    # 🆕 LOG ROTATION
    # ==========================================
    LOG_ROTATION_MAX_BYTES   = get_int_env("LOG_ROTATION_MAX_BYTES", 10_485_760)  # 10 MB
    LOG_ROTATION_BACKUP_COUNT = get_int_env("LOG_ROTATION_BACKUP_COUNT", 5)

    # ==========================================
    # 🆕 ERROR TRACKING (optional)
    # ==========================================
    # Để trống nếu không dùng Sentry.
    SENTRY_DSN: str = os.getenv("SENTRY_DSN", "")
