import os
from typing import Any


def get_bool_env(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


def get_int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def get_float_env(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


class Config:
    # ==================== TELEGRAM ====================
    API_ID = get_int_env("API_ID", 0)
    API_HASH = os.getenv("API_HASH", "")
    SESSION_NAME = os.getenv("SESSION_NAME", "session_bot")

    # ==================== DATABASE ====================
    DATABASE_PATH = os.getenv("DATABASE_PATH", "data/code_history.db")
    DB_VACUUM_INTERVAL = get_int_env("DB_VACUUM_INTERVAL", 86400)
    DB_DEDUP_RETENTION = get_int_env("DB_DEDUP_RETENTION", 2592000)
    DB_LOG_RETENTION = get_int_env("DB_LOG_RETENTION", 604800)

    # ==================== LOGGING ====================
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "logs/bot_activity.log")
    ENABLE_DEBUG_LOGS = get_bool_env("ENABLE_DEBUG_LOGS", False)

    # ==================== BROWSER / PLAYWRIGHT (Edge) ====================
    # Use PLAYWRIGHT_CHANNEL=msedge to prefer Edge
    PLAYWRIGHT_CHANNEL = os.getenv("PLAYWRIGHT_CHANNEL", "msedge")
    EDGE_EXECUTABLE_PATH = os.getenv("EDGE_EXECUTABLE_PATH", "")
    EDGE_USER_DATA_DIR = os.getenv("EDGE_USER_DATA_DIR", "browser_profiles/bot_profile")
    HEADLESS_MODE = get_bool_env("HEADLESS_MODE", False)
    PLAYWRIGHT_LAUNCH_ARGS = os.getenv("PLAYWRIGHT_LAUNCH_ARGS", "--no-sandbox --disable-blink-features=AutomationControlled")

    # ==================== RATE LIMITING ====================
    RATE_LIMIT_STRATEGY = os.getenv("RATE_LIMIT_STRATEGY", "sliding_window")
    RATE_LIMIT_WINDOW = get_int_env("RATE_LIMIT_WINDOW", 60)
    RATE_LIMIT_MAX_REQUESTS = get_int_env("RATE_LIMIT_MAX_REQUESTS", 30)
    MIN_DELAY_BETWEEN_SUBMITS = get_float_env("MIN_DELAY_BETWEEN_SUBMITS", 0.5)

    # ==================== CODE VALIDATION defaults (override per-site) ====================
    CODE_MIN_LENGTH = get_int_env("CODE_MIN_LENGTH", 6)
    CODE_MAX_LENGTH = get_int_env("CODE_MAX_LENGTH", 15)
    MIN_ENTROPY = get_float_env("MIN_ENTROPY", 2.3)
    UPPERCASE_MIN_ENTROPY = get_float_env("UPPERCASE_MIN_ENTROPY", 2.9)

    # Site-specific thresholds (can be loaded/overridden at runtime)
    ENTROPY_THRESHOLDS = {
        "default": {"min": MIN_ENTROPY, "uppercase": UPPERCASE_MIN_ENTROPY},
        "mm88": {"min": get_float_env("MM88_MIN_ENTROPY", 2.4), "uppercase": get_float_env("MM88_UPPERCASE_MIN_ENTROPY", 3.0)},
        "llwin": {"min": get_float_env("LLWIN_MIN_ENTROPY", 2.0), "uppercase": get_float_env("LLWIN_UPPERCASE_MIN_ENTROPY", 2.5)},
    }

    LENGTH_RULES = {
        "default": {"min": CODE_MIN_LENGTH, "max": CODE_MAX_LENGTH},
        "mm88": {"min": get_int_env("MM88_CODE_MIN_LENGTH", 6), "max": get_int_env("MM88_CODE_MAX_LENGTH", 16)},
        "llwin": {"min": get_int_env("LLWIN_CODE_MIN_LENGTH", 4), "max": get_int_env("LLWIN_CODE_MAX_LENGTH", 15)},
    }

    MIN_OCR_CONFIDENCE = {
        "default": get_float_env("OCR_CONFIDENCE_THRESHOLD", 0.70),
        "mm88": get_float_env("MM88_OCR_CONFIDENCE", 0.80),
        "llwin": get_float_env("LLWIN_OCR_CONFIDENCE", 0.85),
    }

    # ==================== RETRY STRATEGY ====================
    RETRY_STRATEGY = os.getenv("RETRY_STRATEGY", "exponential_backoff")
    MAX_RETRY_ATTEMPTS = get_int_env("MAX_RETRY_ATTEMPTS", 2)
    RETRY_BASE_DELAY = get_float_env("RETRY_BASE_DELAY", 2.0)
    RETRY_MAX_DELAY = get_float_env("RETRY_MAX_DELAY", 30.0)
    RETRY_BACKOFF_FACTOR = get_float_env("RETRY_BACKOFF_FACTOR", 1.5)
    RETRY_ON_TIMEOUT = get_bool_env("RETRY_ON_TIMEOUT", True)

    # ==================== MONITORING & QUALITY ====================
    ENABLE_HEARTBEAT = get_bool_env("ENABLE_HEARTBEAT", True)
    HEARTBEAT_INTERVAL = get_float_env("HEARTBEAT_INTERVAL", 300.0)
    ENABLE_TELEGRAM_ALERTS = get_bool_env("ENABLE_TELEGRAM_ALERTS", True)
    QUALITY_ALERT_THRESHOLD = get_float_env("QUALITY_ALERT_THRESHOLD", 0.60)

    # ==================== DEDUP & CACHE ====================
    SITE_CODE_DEDUP_TTL = get_float_env("SITE_CODE_DEDUP_TTL", 30.0)
    PENDING_IMAGE_TTL = get_int_env("PENDING_IMAGE_TTL", 180)
    PENDING_IMAGE_MAX_QUEUE = get_int_env("PENDING_IMAGE_MAX_QUEUE", 100)
    INPUT_CACHE_TTL = get_float_env("INPUT_CACHE_TTL", 20.0)
