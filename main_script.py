"""
🤖 BOT v7.5 - PRODUCTION READY (ALL BUGS FIXED & OPTIMIZED)

MAJOR FIXES in v7.5:
  ✅ sequential_updates=True (False gây drop updates trên DC5)
  ✅ BOT_START_TIME hiển thị cả giờ VN lẫn UTC — không lộn nữa
  ✅ BOT_START_TIME set TRƯỚC client.start(), reset SAU preload
  ✅ Handler: bỏ random delay, thêm RAW log debug
  ✅ Main loop: log đầy đủ exception traceback
  ✅ run_until_disconnected() có debug log xác nhận chạy
  ✅ Filter tin cũ: so sánh UTC với UTC chuẩn xác
"""

from __future__ import annotations  # ✅ FIX: Python 3.9 compatibility (X | Y type syntax)

import asyncio
import csv
import json
import re
import time
import random
import traceback
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from telethon import TelegramClient, events
from telethon.tl.types import MessageEntitySpoiler
from telethon.network import ConnectionTcpAbridged
from playwright.async_api import async_playwright
from camoufox.async_api import AsyncCamoufox
import ctypes, ctypes.wintypes  # Windows taskbar minimize/restore

from config import Config
from logger_setup import logger
from code_validator import CodeValidator
from image_code_extractor import get_image_extractor
from database import init_database
from rate_limiter import init_anti_detection
from monitoring import init_monitoring
from features import print_version_info, get_shutdown_handler
# browser_manager (Edge+CDP) đã loại bỏ — v7.5 dùng Playwright tự launch


# ============================================================
# DOMAIN-SPECIFIC SUBMIT BUTTON SELECTORS
# ============================================================
SUBMIT_BUTTON_SELECTORS = {
    "mm88code.com":    "img.submit-btn, .submit-button-container img, .submit-btn",
    "llwincode.com":   'img[src*="btnnhancode" i], img[alt*="nhan" i]',
    "xx88code.com":    'button[type="submit"], .submit-btn, img.submit-btn, button[class*="submit" i]',
    "o8code.com":      ".modal-submit-btn",
    "new88b.today":    'button[aria-label*="Kiểm tra" i]',
    "tangquaqq88.com": 'button[aria-label*="Kiểm tra" i]',
    "uy88code.org":    "#casinoSubmit",
    "mmoocode.shop":   "#casinoSubmit",
}


# ============================================================
# BOT STATE
# ============================================================
class BotState:
    def __init__(self):
        self.playwright_instance = None
        self.connected_browsers = {}
        self.account_pages = {}
        self.context_locks = {}
        self.is_running = True
        self.cf_verified = {}
        self.submission_count = {}
        self._input_cache: dict = {}
        self._input_cache_ttl = 20.0
        self._site_code_seen: dict = {}
        # ✅ FIX: _site_code_ttl đã bỏ (dead code) — is_site_code_duplicate() đọc Config.SITE_CODE_DEDUP_TTL trực tiếp
        self._page_urls: dict = {}
        self.handler_registered = False
        self._last_cleanup_time = time.time()
        # ✅ UY88 FIX: theo dõi ảnh chưa có caption, chờ MessageEdited
        # key = (chat_id, message_id), value = (event, timestamp_received)
        self._pending_image_msgs: dict = {}
        self._PENDING_IMAGE_TTL: float = getattr(
            Config, "PENDING_IMAGE_TTL", 180.0
        )  # lấy từ config
        # g) Tab fail counter - đếm số lần submit thất bại liên tiếp
        self._tab_fail_count: dict = {}  # key → số lần fail liên tiếp
        self._TAB_FAIL_THRESHOLD: int = getattr(Config, "TAB_FAIL_THRESHOLD", 5)

        # ✅ SINGLE-WINDOW PER CHANNEL + DAILY ACCOUNT TRACKING
        # Mỗi kênh chỉ dùng 1 tab tại 1 thời điểm; xoay tài khoản sau khi nhập thành công
        # _channel_account_index: {channel_key} → index tài khoản hiện tại đang dùng
        self._channel_account_index: dict = {}
        # _daily_used: {(date_str, channel_key, username)} → đánh dấu tài khoản đã nhập xong trong ngày
        self._daily_used: set = set()
        # _daily_date: ngày hiện tại để reset _daily_used mỗi ngày mới
        self._daily_date: str = datetime.now().strftime("%Y-%m-%d")


bot_state = BotState()

# BOT_START_TIME sẽ được set trong main() sau khi client.start() xong
# Dùng giờ local VN (UTC+7) để hiển thị đúng, so sánh nội bộ vẫn dùng UTC
BOT_START_TIME: datetime = datetime.now(timezone.utc)  # placeholder, overridden in main()

# Telegram client - optimized for non-blocking
client = TelegramClient(
    Config.SESSION_NAME,
    Config.API_ID,
    Config.API_HASH,
    device_model="Desktop Bot",
    system_version="Windows 10",
    app_version="1.0",
    connection=ConnectionTcpAbridged,
    connection_retries=5,
    retry_delay=1,
    auto_reconnect=True,
    use_ipv6=False,
    flood_sleep_threshold=60,
    receive_updates=True,
    sequential_updates=True,   # ✅ FIX v7.5: True = tránh drop updates trên DC5 (False gây mất tin)
)

# Global state
_systems = None
message_queue: asyncio.Queue = None
message_workers: list = []
_history_queue: asyncio.Queue = None
_history_writer_task = None
_submit_semaphore: asyncio.Semaphore | None = None
_domain_semaphores: dict = {}  # mỗi domain có semaphore riêng → chạy song song thật
_active_submit_tasks: set[asyncio.Task] = set()

# ============================================================
# HELPERS & UTILITIES
# ============================================================


def normalize_domain(url: str) -> str:
    """Normalize URL to domain."""
    parsed = urlparse(url or "")
    domain = parsed.netloc or parsed.path
    return domain.lower().replace("www.", "").strip("/")


def select_random_code(codes: list) -> str:
    """Select random code from list."""
    if not codes:
        return None
    return random.choice(codes)


def _today_str() -> str:
    """Get today's date string (YYYY-MM-DD)."""
    return datetime.now().strftime("%Y-%m-%d")


def _refresh_daily_state():
    """Reset daily tracking nếu qua ngày mới."""
    today = _today_str()
    if bot_state._daily_date != today:
        bot_state._daily_used.clear()
        bot_state._channel_account_index.clear()
        bot_state._daily_date = today
        logger.info(f"🗓️ Ngày mới ({today}) — đã reset daily account tracking")


def _mark_account_done_today(channel_key: str, username: str):
    """Đánh dấu tài khoản đã nhập code thành công hôm nay."""
    _refresh_daily_state()
    bot_state._daily_used.add((_today_str(), channel_key, username))
    logger.info(f"✅ [DAILY] {channel_key} | {username} → đã đánh dấu dùng hôm nay")


def _is_account_done_today(channel_key: str, username: str) -> bool:
    """Kiểm tra tài khoản đã nhập thành công hôm nay chưa."""
    _refresh_daily_state()
    return (_today_str(), channel_key, username) in bot_state._daily_used


def _get_next_available_account(channel_key: str, accounts: list) -> dict | None:
    """
    Lấy tài khoản kế tiếp chưa nhập hôm nay cho kênh này.
    Trả về None nếu tất cả tài khoản đã nhập xong.
    """
    _refresh_daily_state()
    sorted_accounts = sorted(accounts, key=lambda a: a.get("priority", 999))
    for acc in sorted_accounts:
        if not _is_account_done_today(channel_key, acc["username"]):
            return acc
    return None  # Tất cả đã dùng hết hôm nay


def _is_channel_all_done_today(channel_key: str, accounts: list) -> bool:
    """Kiểm tra tất cả tài khoản của kênh đã nhập xong hôm nay chưa."""
    return _get_next_available_account(channel_key, accounts) is None


def _is_mm88_active_hours() -> bool:
    """MM88 chỉ hoạt động từ 12:00 đến 16:00."""
    now = datetime.now()
    return 12 <= now.hour < 16


# Code history logging
CODE_HISTORY_DIR = Path("logs/code_history")
CODE_HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _write_history_row(row: dict):
    """Write one row to CSV and JSONL."""
    try:
        fieldnames = [
            "time",
            "event_type",
            "channel",
            "site",
            "account",
            "code",
            "source",
            "status",
            "telegram_delay",
            "submit_elapsed",
            "message",
            "screenshot",
        ]
        csv_path = CODE_HISTORY_DIR / f"code_history_{_today_str()}.csv"
        jsonl_path = CODE_HISTORY_DIR / f"code_history_{_today_str()}.jsonl"

        write_header = not csv_path.exists()
        with csv_path.open("a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

        with jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"⚠️ Cannot write code history: {e}")


async def _history_writer_loop():
    """Background worker for history writing."""
    global _history_queue
    while True:
        try:
            row = await _history_queue.get()
            if row is None:
                break
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _write_history_row, row)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"⚠️ history_writer_loop error: {e}")
        finally:
            try:
                _history_queue.task_done()
            except Exception:
                pass


def start_history_writer():
    """Start background history writer task."""
    global _history_queue, _history_writer_task
    _history_queue = asyncio.Queue(maxsize=2000)
    _history_writer_task = asyncio.create_task(_history_writer_loop())
    logger.info("✅ Background history writer started")


def get_submit_semaphore() -> asyncio.Semaphore:
    """Get or create GLOBAL submit semaphore (legacy fallback)."""
    global _submit_semaphore
    if _submit_semaphore is None:
        limit = max(1, int(getattr(Config, "MAX_CONCURRENT_SUBMITS", 2)))
        _submit_semaphore = asyncio.Semaphore(limit)
    return _submit_semaphore


def get_domain_semaphore(domain: str) -> asyncio.Semaphore:
    """
    Semaphore RIÊNG cho mỗi domain → các domain khác nhau submit SONG SONG
    hoàn toàn, không phải xếp hàng chờ chung 1 semaphore global.
    Mỗi domain vẫn giới hạn concurrent submit nội bộ (theo MAX_CONCURRENT_SUBMITS)
    để tránh đụng 2 tab cùng lúc trên cùng 1 site.
    """
    global _domain_semaphores      
    if domain not in _domain_semaphores:
        limit = max(1, int(getattr(Config, "MAX_CONCURRENT_SUBMITS_PER_DOMAIN", 2)))
        _domain_semaphores[domain] = asyncio.Semaphore(limit)
    return _domain_semaphores[domain]


def append_code_history(
    event_type: str,
    code: str = "",
    target_url: str = "",
    account: str = "",
    channel: str = "",
    source: str = "",
    status: str = "",
    telegram_delay=None,
    submit_elapsed=None,
    message: str = "",
    screenshot: str = "",
):
    """Queue code history entry."""
    try:
        row = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event_type": event_type,
            "channel": channel or "",
            "site": normalize_domain(target_url),
            "account": account or "",
            "code": str(code or ""),
            "source": source or "",
            "status": status or "",
            "telegram_delay": (
                "" if telegram_delay is None else f"{float(telegram_delay):.2f}"
            ),
            "submit_elapsed": (
                "" if submit_elapsed is None else f"{float(submit_elapsed):.2f}"
            ),
            "message": str(message or "").replace("\n", " ")[:300],
            "screenshot": str(screenshot or ""),
        }
        if _history_queue is not None:
            try:
                _history_queue.put_nowait(row)
            except asyncio.QueueFull:
                logger.debug("⚠️ History queue full")
        else:
            _write_history_row(row)
        return row
    except Exception as e:
        logger.debug(f"⚠️ Cannot enqueue code history: {e}")
        return None


# ============================================================
# DEDUPLICATION
# ============================================================


def _prune_site_code_seen():
    """Clean expired entries from dedup cache."""
    ttl = float(getattr(Config, "SITE_CODE_DEDUP_TTL", 10.0))
    now = time.time()
    expired = [k for k, ts in bot_state._site_code_seen.items() if now - ts > ttl]
    for k in expired:
        del bot_state._site_code_seen[k]


async def _cleanup_scheduler():
    """Periodically clean up memory caches."""
    while bot_state.is_running:
        try:
            await asyncio.sleep(
                float(getattr(Config, "INPUT_CACHE_CLEANUP_INTERVAL", 300))
            )
            _prune_site_code_seen()
            # ✅ UY88 FIX: dọn pending image messages quá TTL
            expired = await _cleanup_pending_images()
            if expired:
                logger.info(f"🧹 Cleaned {expired} expired pending image(s)")
            else:
                logger.debug("🧹 Cleanup done")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"⚠️ Cleanup error: {e}")


def is_site_code_duplicate(domain: str, code: str) -> bool:
    """Check if code was recently submitted to this domain."""
    ttl = float(getattr(Config, "SITE_CODE_DEDUP_TTL", 10.0))
    now = time.time()
    _prune_site_code_seen()
    key = (domain, code.upper())
    seen_at = bot_state._site_code_seen.get(key)
    if seen_at is not None and now - seen_at < ttl:
        return True
    bot_state._site_code_seen[key] = now
    return False


def build_daily_summary():
    """Build end-of-day summary report."""
    try:
        csv_path = CODE_HISTORY_DIR / f"code_history_{_today_str()}.csv"
        if not csv_path.exists():
            return None

        summary = {}
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("event_type") != "RESULT":
                    continue
                key = (row.get("site", ""), row.get("account", ""))
                if key not in summary:
                    summary[key] = {"SUCCESS": 0, "FAILED": 0, "UNKNOWN": 0}
                status = row.get("status") or "UNKNOWN"
                summary[key].setdefault(status, 0)
                summary[key][status] += 1

        out_path = CODE_HISTORY_DIR / f"daily_summary_{_today_str()}.csv"
        with out_path.open("w", newline="", encoding="utf-8-sig") as f:
            fieldnames = [
                "date",
                "site",
                "account",
                "success",
                "failed",
                "unknown",
                "total",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for (site, account), counts in sorted(summary.items()):
                s = counts.get("SUCCESS", 0)
                fa = counts.get("FAILED", 0)
                u = counts.get("UNKNOWN", 0)
                writer.writerow(
                    {
                        "date": _today_str(),
                        "site": site,
                        "account": account,
                        "success": s,
                        "failed": fa,
                        "unknown": u,
                        "total": s + fa + u,
                    }
                )
        logger.info(f"📒 Daily summary: {out_path}")
        return str(out_path)
    except Exception as e:
        logger.warning(f"⚠️ Cannot create daily summary: {e}")
        return None


def measure_telegram_delay_fast(msg_timestamp) -> float | None:
    """Measure Telegram message delay."""
    try:
        if msg_timestamp.tzinfo is None:
            msg_timestamp = msg_timestamp.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - msg_timestamp).total_seconds()
    except Exception:
        return None


def build_unique_account_targets():
    """
    Build list of unique domain targets with accounts.

    LOGIC MỚI:
    - Mỗi kênh (domain) chỉ mở 1 tab duy nhất, tài khoản xoay sau khi thành công
    - MM88: mở đúng 2 tab (1 tab/account) để submit song song
    - Nếu tất cả tài khoản của kênh đã dùng hôm nay → KHÔNG mở tab cho kênh đó
    - MM88 ngoài giờ 12:00-16:00 → KHÔNG mở tab
    """
    items = []
    seen_domains = set()

    sorted_channels = sorted(
        Config.CHANNEL_CONFIG.items(),
        key=lambda item: item[1].get("priority", 999),
    )

    for chat_id, channel_config in sorted_channels:
        target_url = channel_config["url"]
        domain = normalize_domain(target_url)

        if domain in seen_domains:
            continue
        seen_domains.add(domain)

        accounts = channel_config.get("accounts", [])
        if not accounts:
            continue

        sorted_accounts = sorted(accounts, key=lambda a: a.get("priority", 999))

        # ── MM88: 2 tab song song ─────────────────────────────────────────
        if domain == "mm88code.com":
            # Kiểm tra giờ hoạt động MM88
            if not _is_mm88_active_hours():
                logger.info(
                    f"⏰ [MM88] Ngoài giờ hoạt động (12:00-16:00) → KHÔNG mở tab"
                )
                continue

            # Lọc tài khoản chưa dùng hôm nay (dùng domain|username làm channel_key)
            available = [
                acc for acc in sorted_accounts
                if not _is_account_done_today(f"{domain}|{acc['username']}", acc["username"])
            ]
            if not available:
                logger.info(f"✅ [MM88] Tất cả tài khoản đã nhập xong hôm nay → KHÔNG mở tab")
                continue

            for acc in available:
                items.append(
                    {
                        "chat_id": chat_id,
                        "channel_name": channel_config.get("name", ""),
                        "target_url": target_url,
                        "domain": domain,
                        "key": f"{domain}|{acc['username']}",
                        "port": get_user_port(acc["username"]),
                        "accounts": [acc],
                    }
                )
            continue

        # ── Các kênh khác: 1 tab duy nhất ───────────────────────────────
        # Kiểm tra còn tài khoản nào chưa dùng hôm nay không
        next_acc = _get_next_available_account(domain, sorted_accounts)
        if next_acc is None:
            logger.info(
                f"✅ [{domain}] Tất cả {len(sorted_accounts)} tài khoản đã nhập xong hôm nay → KHÔNG mở tab"
            )
            continue

        port = get_user_port(next_acc["username"])
        items.append(
            {
                "chat_id": chat_id,
                "channel_name": channel_config.get("name", ""),
                "target_url": target_url,
                "domain": domain,
                "key": domain,
                "port": port,
                "accounts": sorted_accounts,  # Toàn bộ list để xoay vòng
            }
        )

    return items


def get_user_port(user: str) -> int:
    """Legacy stub - v7.5 dung Playwright profile thay vi CDP port."""
    return 0


def get_user_profile_dir(user: str) -> str:
    """Tra ve duong dan thu muc profile Playwright cho user.
    user="shared" → profile chung, tất cả tab trong 1 cửa sổ.
    """
    import os
    base = getattr(Config, "BROWSER_PROFILE_BASE_DIR", "browser_profiles")
    if user == "shared":
        return os.path.join(base, "shared")
    return os.path.join(base, user)


_playwright_contexts: dict = {}
_playwright_context_locks: dict = {}
_camoufox_instance = None  # Camoufox browser instance (thay Playwright Chromium)
_camoufox_launch_lock = None  # Global lock — chỉ 1 instance được tạo
_shared_context = None  # 1 context duy nhất dùng chung cho tất cả tab


def _get_launch_lock():
    global _camoufox_launch_lock
    if _camoufox_launch_lock is None:
        _camoufox_launch_lock = asyncio.Lock()
    return _camoufox_launch_lock


async def get_or_launch_browser_context(user: str):
    """
    Luôn trả về CÙNG 1 context duy nhất — tất cả tab chạy trong 1 cửa sổ.
    Global lock đảm bảo không bao giờ tạo 2 instance song song.
    """
    global _camoufox_instance, _shared_context

    # Fast path: context đã có rồi
    if _shared_context is not None:
        try:
            _ = _shared_context.pages
            return _shared_context
        except Exception:
            _shared_context = None

    async with _get_launch_lock():
        # Double-check sau khi có lock
        if _shared_context is not None:
            try:
                _ = _shared_context.pages
                return _shared_context
            except Exception:
                _shared_context = None

        headless = getattr(Config, "HEADLESS_MODE", False)
        logger.info(f"[Camoufox] Launch browser (1 instance duy nhất)")

        if _camoufox_instance is None:
            mon = _get_secondary_monitor_rect()          # ← màn hình PHỤ (1600x900)
            mon_w = mon["right"]  - mon["left"]
            mon_h = mon["bottom"] - mon["top"]
            # Xáo trộn nội bộ: kích thước dao động ±5% để tránh fingerprint cố định
            import random as _rnd
            scale_w = _rnd.uniform(0.88, 0.96)
            scale_h = _rnd.uniform(0.88, 0.96)
            win_w = int(mon_w * scale_w)
            win_h = int(mon_h * scale_h)
            # Offset nhỏ từ góc trên-trái để không bị cắt viền
            off_x = _rnd.randint(0, max(0, mon_w - win_w))
            off_y = _rnd.randint(0, max(0, 30))
            _camoufox_instance = await AsyncCamoufox(
                headless=headless,
                geoip=True,
                os="windows",
                screen={"width": mon_w, "height": mon_h},
                viewport={"width": win_w, "height": win_h},
            ).__aenter__()
            logger.info(f"[Camoufox] Browser launched thành công")
            # Ghim cửa sổ vào màn hình PHỤ
            await asyncio.sleep(1.0)
            hwnd = _find_camoufox_hwnd()
            if hwnd:
                ctypes.windll.user32.MoveWindow(
                    hwnd,
                    mon["left"] + off_x,   # X tuyệt đối trên màn phụ
                    mon["top"]  + off_y,   # Y tuyệt đối trên màn phụ
                    win_w, win_h,
                    True,
                )
                logger.info(
                    f"[Camoufox] Cửa sổ → màn phụ ({win_w}x{win_h} "
                    f"@ {mon['left']+off_x},{mon['top']+off_y})"
                )

        # Luôn dùng contexts[0] — 1 context duy nhất
        if _camoufox_instance.contexts:
            _shared_context = _camoufox_instance.contexts[0]
        else:
            _shared_context = await _camoufox_instance.new_context()

        logger.info(f"[Camoufox] Shared context sẵn sàng — tất cả tab dùng chung")
        return _shared_context



def get_default_account_for_domain(domain_key: str) -> str | None:
    """Get default account for domain (watchdog use)."""
    if "|" in domain_key:
        domain, user = domain_key.split("|", 1)
        return user
    domain = domain_key
    for chat_id, cfg in Config.CHANNEL_CONFIG.items():
        if normalize_domain(cfg["url"]) == domain:
            accounts = cfg.get("accounts", [])
            if accounts:
                return sorted(accounts, key=lambda a: a.get("priority", 999))[0][
                    "username"
                ]
    return None


# ============================================================
# BROWSER INITIALIZATION
# ============================================================


async def verify_telegram_session():
    """Verify Telegram session is valid."""
    logger.info("\n" + "=" * 70)
    logger.info("🔐 VERIFYING TELEGRAM SESSION...")
    try:
        me = await client.get_me()
        dc_id = client.session.dc_id
        dc_names = {
            1: "DC1 Miami 🇺🇸",
            2: "DC2 Amsterdam 🇳🇱",
            3: "DC3 Miami 🇺🇸",
            4: "DC4 Amsterdam 🇳🇱",
            5: "DC5 Singapore 🇸🇬",
        }
        dc_label = dc_names.get(dc_id, f"DC{dc_id} Unknown")
        logger.info(f"✅ SESSION VALID! @{me.username} (ID: {me.id})")
        logger.info(
            f"📡 Telegram DC: {dc_label} — {'✅ Tốt cho VN' if dc_id == 5 else '⚠️ Xa VN, có thể delay'}"
        )
        return True
    except Exception as e:
        logger.error(f"❌ SESSION ERROR: {e}")
        return False


async def verify_channels_and_get_ids():
    """Verify all configured channels are accessible.

    ✅ FIX: KHÔNG dùng client.iter_dialogs() để tải toàn bộ danh sách dialog nữa.
    Với account có nhiều group/channel/contact, iter_dialogs() có thể "treo" rất
    lâu (hoặc gần như vô hạn) trước khi vào loop kiểm tra → bot không bao giờ
    chạy tới preload_browsers_and_accounts() → browser mở nhưng không vào trang.

    Thay vào đó: kiểm tra TRỰC TIẾP từng channel trong CHANNEL_CONFIG bằng
    client.get_entity(chat_id), có timeout riêng cho từng channel nên không thể
    treo cả tiến trình dù 1 channel bị lỗi/chậm.
    """
    logger.info("\n" + "=" * 70)
    logger.info("📡 VERIFYING CHANNELS...")
    valid_channels = {}

    for chat_id, channel_config in Config.CHANNEL_CONFIG.items():
        name = channel_config.get("name", str(chat_id))
        try:
            await asyncio.wait_for(client.get_entity(chat_id), timeout=10.0)
            logger.info(f"✅ VALID: {name}")
            valid_channels[chat_id] = channel_config
        except asyncio.TimeoutError:
            logger.warning(f"⏰ TIMEOUT 10s: {name} (chat_id={chat_id}) — bỏ qua, không chặn bot")
        except Exception as e:
            logger.warning(f"❌ NOT JOINED / LỖI: {name} - {e}")

    logger.info(f"📋 Tổng channel hợp lệ: {len(valid_channels)}/{len(Config.CHANNEL_CONFIG)}")
    return valid_channels


async def init_systems():
    """Initialize all systems."""
    print_version_info()
    db = init_database(Config.DATABASE_PATH)
    anti_det = init_anti_detection()
    _, _, perf_mon = init_monitoring()

    # ✅ v7.5+: Camoufox thay Playwright — không cần playwright_instance nữa
    # bot_state.playwright_instance dùng làm sentinel check ở một số chỗ → set dummy
    bot_state.playwright_instance = True
    get_shutdown_handler().setup(bot_state)

    start_history_writer()

    return {
        "db": db,
        "anti_detection": anti_det,
        "performance_monitor": perf_mon,
    }


CF_SELECTORS = [
    "iframe[src*='turnstile']",
    "iframe[src*='challenges.cloudflare.com']",
    ".cf-turnstile",
    "[data-sitekey]",
]


async def notify_admin(msg: str):
    """Gửi thông báo về Telegram cho admin khi cần xác minh thủ công."""
    try:
        admin_id = getattr(Config, "TELEGRAM_ADMIN_ID", 0)
        if admin_id and client and client.is_connected():
            await client.send_message(admin_id, msg)
    except Exception as e:
        logger.debug(f"notify_admin error: {e}")


# ── Camoufox window: minimize xuống taskbar / restore lên ──────────────────
_camoufox_hwnd: int = 0  # cache HWND của cửa sổ Camoufox

def _find_camoufox_hwnd() -> int:
    """
    Tìm HWND chính của Camoufox — lấy cửa sổ có diện tích LỚN NHẤT.
    Đồng thời ẩn (SW_HIDE) tất cả cửa sổ Camoufox phụ để chỉ còn 1.
    """
    global _camoufox_hwnd
    if _camoufox_hwnd:
        if ctypes.windll.user32.IsWindow(_camoufox_hwnd):
            return _camoufox_hwnd
        _camoufox_hwnd = 0

    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                      ctypes.wintypes.HWND,
                                      ctypes.wintypes.LPARAM)
    def _cb(hwnd, _):
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.lower()
        if any(k in title for k in ("firefox", "camoufox", "mozilla", "new tab")):
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right  - rect.left
            h = rect.bottom - rect.top
            if w > 100 and h > 50:   # bỏ qua toolbar/tooltip nhỏ xíu
                found.append((w * h, hwnd))
        return True

    ctypes.windll.user32.EnumWindows(WNDENUMPROC(_cb), 0)
    if not found:
        return 0

    # Lấy cửa sổ to nhất = cửa sổ chính
    found.sort(key=lambda x: x[0], reverse=True)
    _camoufox_hwnd = found[0][1]

    # Ẩn tất cả cửa sổ phụ (nhỏ hơn) — chỉ giữ cửa sổ chính
    for _, hwnd in found[1:]:
        try:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
        except Exception:
            pass

    return _camoufox_hwnd


def camoufox_minimize():
    """Minimize cửa sổ Camoufox xuống taskbar."""
    try:
        hwnd = _find_camoufox_hwnd()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE = 6
            logger.debug("🔽 Camoufox minimized xuống taskbar")
    except Exception as e:
        logger.debug(f"camoufox_minimize error: {e}")


def _get_primary_monitor_rect():
    """Lấy tọa độ tuyệt đối của primary monitor (màn hình 1)."""
    monitors = []
    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.wintypes.HMONITOR,
        ctypes.wintypes.HDC,
        ctypes.POINTER(ctypes.wintypes.RECT),
        ctypes.wintypes.LPARAM,
    )
    def _cb(hmon, hdc, rect_ptr, _):
        r = rect_ptr.contents
        info = ctypes.create_string_buffer(40)
        ctypes.c_uint32.from_address(ctypes.addressof(info)).value = 40
        ctypes.windll.user32.GetMonitorInfoW(hmon, info)
        # dwFlags offset 36 = MONITORINFOF_PRIMARY (1)
        flags = ctypes.c_uint32.from_address(ctypes.addressof(info) + 36).value
        monitors.append({
            "left": r.left, "top": r.top,
            "right": r.right, "bottom": r.bottom,
            "primary": bool(flags & 1),
        })
        return True
    ctypes.windll.user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0)
    for m in monitors:
        if m["primary"]:
            return m
    # Fallback: monitor đầu tiên
    return monitors[0] if monitors else {"left": 0, "top": 0, "right": 1600, "bottom": 900, "primary": True}


def _get_secondary_monitor_rect():
    """
    Lấy tọa độ màn hình PHỤ (non-primary).
    Nếu chỉ có 1 màn hình → fallback về primary.
    """
    monitors = []
    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.wintypes.HMONITOR,
        ctypes.wintypes.HDC,
        ctypes.POINTER(ctypes.wintypes.RECT),
        ctypes.wintypes.LPARAM,
    )
    def _cb(hmon, hdc, rect_ptr, _):
        r = rect_ptr.contents
        info = ctypes.create_string_buffer(40)
        ctypes.c_uint32.from_address(ctypes.addressof(info)).value = 40
        ctypes.windll.user32.GetMonitorInfoW(hmon, info)
        flags = ctypes.c_uint32.from_address(ctypes.addressof(info) + 36).value
        monitors.append({
            "left": r.left, "top": r.top,
            "right": r.right, "bottom": r.bottom,
            "primary": bool(flags & 1),
        })
        return True
    ctypes.windll.user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0)
    # Ưu tiên màn phụ
    for m in monitors:
        if not m["primary"]:
            return m
    # Fallback: chỉ có 1 màn → dùng primary
    for m in monitors:
        if m["primary"]:
            return m
    return {"left": 0, "top": 0, "right": 1600, "bottom": 900, "primary": True}


def camoufox_restore(page=None):
    """Restore Camoufox lên foreground."""
    try:
        hwnd = _find_camoufox_hwnd()
        if not hwnd:
            return
        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception as e:
        logger.debug(f"camoufox_restore error: {e}")


async def is_cloudflare_present(page) -> bool:
    """Kiểm tra widget Turnstile/Cloudflare có đang hiện trên trang không
    (bất kể đang pending hay đã 'Xác minh thất bại'). Dùng chung cho cả
    bước preload (mở tab lần đầu) và bước submit code, để KHÔNG tự động
    tương tác (fill/click) vào trang khi chưa rõ trạng thái xác minh —
    việc xác minh luôn để người dùng làm tay."""
    for sel in CF_SELECTORS:
        try:
            el = await page.query_selector(sel)
            if el and await safe_is_visible(el):
                return True
        except Exception:
            pass
    return False


async def safe_is_visible(element) -> bool:
    """Safely check if element is visible."""
    try:
        return await element.is_visible()
    except Exception:
        return False


def _invalidate_input_cache(key: str):
    """Invalidate input field cache."""
    bot_state._input_cache.pop(key, None)


async def find_input_fields(page, cache_key: str = None):
    """Find username and code input fields with caching."""
    now = time.time()

    # Check cache
    if cache_key:
        cached = bot_state._input_cache.get(cache_key)
        if cached:
            username_input, code_input, cache_time = cached
            if now - cache_time < bot_state._input_cache_ttl:
                try:
                    if code_input:
                        visible = await code_input.is_visible()
                        if visible:
                            return username_input, code_input
                    _invalidate_input_cache(cache_key)
                except Exception:
                    _invalidate_input_cache(cache_key)

    username_input = None
    code_input = None

    username_selectors = [
        "#account-code",
        "#username-input",
        "#ten_tai_khoan",
        "input#username",
        "input[name='username']",
        "input[placeholder*='người dùng' i]",
        "input[placeholder*='tên' i]",
        "input[placeholder*='tài' i]",
        "input[placeholder*='tài khoản' i]",
        "input[placeholder*='user' i]",
        "input[placeholder*='đăng nhập' i]",
        "input[name='ten_tai_khoan']",
        "input[id='username']",
        "input[type='text']",
    ]

    code_selectors = [
        "#promo-code",
        "#giftcode-input",
        "input[autocomplete='one-time-code']",
        "input#code",
        "input[name='code']",
        "input[placeholder*='mã code' i]",
        "input[placeholder*='code' i]",
        "input[placeholder*='mã' i]",
        "input[name='giftcode']",
        "input[id='code']",
        "input[id*='code' i]",
        "input[id*='promo' i]",
    ]

    try:
        # Find username input
        for selector in username_selectors:
            try:
                element = await page.query_selector(selector)
                if element and await safe_is_visible(element):
                    username_input = element
                    break
            except Exception:
                pass

        # Find code input
        for selector in code_selectors:
            try:
                element = await page.query_selector(selector)
                if element and await safe_is_visible(element):
                    code_input = element
                    break
            except Exception:
                pass

        # Fallback: find visible inputs
        if not username_input or not code_input:
            inputs = await page.query_selector_all(
                "input:not([type='hidden']):not([type='checkbox'])"
                ":not([type='radio']):not([type='submit'])"
            )
            visible_inputs = []
            for inp in inputs:
                if await safe_is_visible(inp):
                    visible_inputs.append(inp)

            if len(visible_inputs) >= 2:
                if not username_input:
                    username_input = visible_inputs[0]
                if not code_input:
                    code_input = visible_inputs[1]
            elif len(visible_inputs) == 1:
                if not code_input:
                    code_input = visible_inputs[0]

    except Exception as e:
        logger.debug(f"⚠️ Error finding input fields: {e}")

    # Only cache if code_input found
    if cache_key and code_input:
        bot_state._input_cache[cache_key] = (username_input, code_input, now)

    return username_input, code_input


# ============================================================
# SCROLL TO INPUT FIELDS
# ============================================================


async def scroll_to_input_fields(page):
    """Cuộn tới input field để hiển thị & chuẩn bị cho Cloudflare"""
    try:
        found = await page.evaluate("""
            () => {
                const inputs = document.querySelectorAll('input[type="text"], input:not([type="hidden"])');
                if (inputs.length > 0) {
                    const firstInput = inputs[0];
                    firstInput.scrollIntoView({behavior: 'smooth', block: 'center'});
                    firstInput.focus();
                    return true;
                }
                return false;
            }
        """)
        await asyncio.sleep(0.1)
        if found:
            logger.debug("✅ Scrolled to input fields")
        else:
            logger.warning(
                "⚠️ scroll_to_input_fields: không tìm thấy input nào trên trang"
            )
        return found
    except Exception as e:
        logger.debug(f"⚠️ Scroll error: {e}")
        return False


async def get_input_value(input_element) -> str:
    """Get current value from input element."""
    try:
        return (await input_element.input_value(timeout=1000)).strip()
    except Exception:
        return ""


# ============================================================
# SUBMIT BUTTON CLICKING
# ============================================================


async def click_submit_fast(page, domain: str = "") -> bool:
    """Click submit button with domain-specific selectors first."""
    # ✅ Thêm random delay trước khi click (giống người dùng)
    await asyncio.sleep(random.uniform(0.3, 0.8))

    # Try domain-specific selector
    domain_sel = SUBMIT_BUTTON_SELECTORS.get(domain)
    if domain_sel:
        try:
            # ✅ FIX: truyền selector qua args để tránh JS injection nếu có dấu nháy đơn
            clicked = await page.evaluate("""
                async (sel) => {
                    const deadline = Date.now() + 600;
                    while (Date.now() < deadline) {
                        const btn = document.querySelector(sel);
                        if (btn && !btn.disabled) {
                            const rect = btn.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                btn.click();
                                return true;
                            }
                        }
                        await new Promise(r => setTimeout(r, 100));
                    }
                    const btn = document.querySelector(sel);
                    if (btn) { btn.click(); return true; }
                    return false;
                }
            """, domain_sel)
            if clicked:
                logger.debug(f"✅ Clicked domain-specific button: {domain}")
                return True
        except Exception:
            pass

    # Try text/aria-label matching
    try:
        clicked = await page.evaluate("""
            () => {
                const keywords = [
                    'kiểm tra ngay', 'kiem tra ngay',
                    'kiểm tra', 'kiem tra',
                    'nhận code', 'nhan code',
                    'nhận ngay', 'nhan ngay',
                    'áp dụng', 'ap dung',
                    'đổi code', 'doi code',
                    'nạp code', 'nap code',
                    'gửi', 'gui',
                    'submit', 'apply'
                ];
                // LOẠI TRỪ: nút CF Turnstile ('xác thực', 'verify', 'check') và nav/menu
                const EXCLUDE = /menu|nav|home|close|cancel|toggle|hamburger|back|trở về|huỷ|hủy|đóng|xác thực|xac thuc|verify|check/i;
                const els = [...document.querySelectorAll(
                    'button, a[role="button"], div[role="button"], span[role="button"], input[type="button"], input[type="submit"]'
                )];
                for (const kw of keywords) {
                    for (const el of els) {
                        if (el.disabled) continue;
                        const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                        const img = el.querySelector('img[alt]');
                        const imgAlt = img ? (img.getAttribute('alt') || '').toLowerCase() : '';
                        const txt = (el.innerText || el.textContent || el.value || '').toLowerCase().trim();
                        if (EXCLUDE.test(aria + txt)) continue;
                        if ([txt, aria, imgAlt].some(s => s && s.includes(kw))) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                el.click();
                                return true;
                            }
                        }
                    }
                }
                return false;
            }
        """)
        if clicked:
            return True
    except Exception:
        pass

    # Try generic selectors
    generic_selectors = [
        "button[type='submit']",
        "input[type='submit']",
        ".btn-submit",
        ".apply-btn",
        ".submit-btn",
        "[class*='submit' i]",
        "[class*='apply' i]",
        # "[class*='check' i]",  # BỎ: có thể khớp CF checkbox/widget
    ]

    for sel in generic_selectors:
        try:
            el = await page.query_selector(sel)
            if el and await safe_is_visible(el):
                await page.evaluate("el => el.click()", el)
                return True
        except Exception:
            pass

    # Last resort: Press Enter
    try:
        await page.keyboard.press("Enter")
        return True
    except Exception:
        return False


# ============================================================
# RESULT DETECTION
# ============================================================


async def _fetch_element_text(page, selector: str) -> str:
    """Fetch text from element(s)."""
    try:
        elements = await page.query_selector_all(selector)
        texts = []
        for el in elements:
            try:
                text = await el.inner_text(timeout=300)
                if text and text.strip():
                    texts.append(text.strip())
            except Exception:
                pass
        return " ".join(texts)
    except Exception:
        return ""


def _filter_nextjs_noise(text: str) -> str:
    """Filter Next.js hydration noise."""
    if not text:
        return ""
    noise_markers = [
        "__next_f",
        "__NEXT",
        "self.__next",
        'push([1,"',
        '"stylesheet"',
        '"link"',
        "webpack",
        "hydrat",
        '"rel":',
        '"href":',
        ':[[["$"',
    ]
    t = text.strip()
    for marker in noise_markers:
        if marker in t:
            return ""
    if t.startswith(('{"', '[["', '[[["', "self.")):
        return ""
    return t


async def detect_result_text(page) -> str:
    """Detect result text on page."""
    PRIORITY_SELECTORS = [
        # SweetAlert2 (dùng phổ biến cho QQ88, NEW88, UY88)
        ".swal2-html-container",
        ".swal2-title",
        ".swal2-popup",
        # QQ88 specific
        "div[class*='popup'] p",
        "div[class*='modal'] p",
        "div[class*='dialog'] p",
        "div[class*='alert'] p",
        "div[class*='notice'] p",
        "div[class*='message'] p",
        # Tailwind classes
        ".text-red-600",
        ".text-green-600",
        ".text-yellow-600",
        ".text-red-500",
        ".text-green-500",
        "p.mt-1.text-sm",
        "div[class*='rounded-2xl'] p",
        "div[class*='rounded-xl'] p",
        "div[class*='rounded-lg'] p",
        # ARIA
        "[role='alert']",
        "[role='status']",
        "[role='dialog']",
        # Fixed/overlay popups
        "div[style*='position: fixed'] p",
        "div[style*='position:fixed'] p",
    ]

    for sel in PRIORITY_SELECTORS:
        try:
            txt = await _fetch_element_text(page, sel)
            if txt and len(txt.strip()) >= 3:
                clean = _filter_nextjs_noise(txt.strip())
                if clean:
                    return clean
        except Exception:
            pass

    result_selectors = [
        ".text-red-600",
        ".text-green-600",
        "p.mt-1.text-sm",
        "div[class*='rounded-2xl'] p",
        "div[class*='rounded-xl'] p",
        "div[class*='rounded-lg'] p",
        "[role='dialog']",
        "[role='alert']",
        "[role='status']",
        ".modal-body",
        ".modal-content",
        ".popup-content",
        ".alert",
        "[class*='success']",
        "[class*='error']",
        "[class*='toast']",
        "[class*='result']",
        "[class*='notify']",
        "[class*='modal']",
        "[class*='popup']",
        "[class*='notification']",
        "div[style*='position: fixed']",
    ]

    tasks = [_fetch_element_text(page, sel) for sel in result_selectors]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    combined = ""

    for r in results:
        if isinstance(r, str) and r.strip():
            filtered = _filter_nextjs_noise(r.strip())
            if filtered:
                combined += filtered + " "

    if len(combined.strip()) >= 3:
        return combined.strip()

    try:
        page_text = await page.evaluate("""
            () => {
                const keywords = [
                    'thành công', 'thanh cong', 'thất bại', 'that bai',
                    'sai', 'lỗi', 'loi', 'đã sử dụng', 'da su dung',
                    'success', 'failed', 'error', 'invalid', 'used',
                    'không hợp lệ', 'khong hop le', 'hết hạn', 'het han',
                    'không đúng', 'không tồn tại',
                ];
                const noisePatterns = ['__next_f', '__NEXT', 'self.__next', 'push([', 'webpack'];
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT, null, false
                );
                let node;
                while (node = walker.nextNode()) {
                    const parent = node.parentElement;
                    if (!parent) continue;
                    const tag = parent.tagName || '';
                    if (['SCRIPT','STYLE','NOSCRIPT'].includes(tag)) continue;
                    const txt = (node.textContent || '').trim();
                    if (txt.length < 3) continue;
                    if (noisePatterns.some(p => txt.includes(p))) continue;
                    const lower = txt.toLowerCase();
                    if (keywords.some(k => lower.includes(k))) return txt;
                }
                return '';
            }
        """)
        if page_text:
            clean = _filter_nextjs_noise(page_text)
            if clean:
                return clean
    except Exception:
        pass

    return ""


async def take_result_screenshot(
    page, user: str, code: str, target_url: str, status: str
) -> str:
    """Take screenshot of result."""
    if not bool(getattr(Config, "SCREENSHOT_ON_UNKNOWN", False)):
        return ""
    try:
        shot_dir = Path("logs/screenshots")
        shot_dir.mkdir(parents=True, exist_ok=True)
        safe_domain = normalize_domain(target_url).replace(".", "_").replace("/", "_")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = shot_dir / f"{safe_domain}_{user}_{code}_{status}_{ts}.png"
        await page.screenshot(path=str(path), full_page=False)
        return str(path)
    except Exception as e:
        logger.debug(f"⚠️ Cannot take screenshot: {e}")
        return ""


async def connect_to_cdp_port(port: int):
    """Connect to CDP port."""
    if port in bot_state.connected_browsers:
        return bot_state.connected_browsers[port]

    logger.info(f"🖥️ Connecting to CDP port {port}...")
    browser = await bot_state.playwright_instance.chromium.connect_over_cdp(
        f"http://127.0.0.1:{port}"
    )
    bot_state.connected_browsers[port] = browser

    logger.info(f"✅ Connected to CDP port {port}")
    return browser


async def _setup_page_performance(page, label: str = ""):
    """Optimize page performance + ẩn dấu hiệu automation khỏi Cloudflare."""

    # ── Ẩn navigator.webdriver và các fingerprint automation ────────────────
    STEALTH_JS = """
        () => {
            // 1. Xóa navigator.webdriver (dấu hiệu Playwright/Puppeteer)
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
                configurable: true,
            });

            // 2. Fake chrome runtime
            if (!window.chrome) {
                window.chrome = {};
            }
            window.chrome.runtime = {};

            // 3. Fake plugins (browser thật luôn có plugins)
            Object.defineProperty(navigator, 'plugins', {
                get: () => {
                    return [
                        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                    ];
                },
                configurable: true,
            });

            // 4. Fake languages mảng
            Object.defineProperty(navigator, 'languages', {
                get: () => ['vi-VN', 'vi', 'en-US', 'en'],
                configurable: true,
            });

            // 5. Xóa $cdc_ (ChromeDriver marker)
            if (window.$cdc_asdjflasutopfhvcZLmcfl_) {
                delete window.$cdc_asdjflasutopfhvcZLmcfl_;
            }

            // 6. Xóa $wdc_ (WebDriver marker)
            if (window.$wdc_) {
                delete window.$wdc_;
            }

            // 7. Mock permissions.query (dùng bởi một số script detect)
            if (navigator.permissions && navigator.permissions.query) {
                const origQuery = navigator.permissions.query;
                navigator.permissions.query = (parameters) =>
                    parameters.name === 'notifications'
                        ? Promise.resolve({ state: Notification.permission })
                        : origQuery(parameters);
            }

            // 8. Overwrite headless detection
            Object.defineProperty(navigator, 'headless', {
                get: () => false,
                configurable: true,
            });

            // 9. Fake reasonable screen properties
            Object.defineProperty(screen, 'width', { get: () => 1920, configurable: true });
            Object.defineProperty(screen, 'height', { get: () => 1080, configurable: true });
            Object.defineProperty(screen, 'availWidth', { get: () => 1920, configurable: true });
            Object.defineProperty(screen, 'availHeight', { get: () => 1040, configurable: true });

            // 10. Fake WebGL Renderer (quan trọng nhất với Turnstile)
            try {
                const getParam = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) return 'Intel Inc.';
                    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                    return getParam.call(this, parameter);
                };
                const getParam2 = WebGL2RenderingContext.prototype.getParameter;
                WebGL2RenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) return 'Intel Inc.';
                    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                    return getParam2.call(this, parameter);
                };
            } catch(e) {}

            // 11. Fake hardwareConcurrency và deviceMemory
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8, configurable: true });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8, configurable: true });

            // 12. Fake connection
            Object.defineProperty(navigator, 'connection', {
                get: () => ({ rtt: 50, downlink: 10, effectiveType: '4g', saveData: false }),
                configurable: true,
            });
        }
    """

    try:
        await page.add_init_script(STEALTH_JS)
        logger.debug(f"✅ [{label}] Stealth JS loaded")
    except Exception as e:
        logger.debug(f"⚠️ [{label}] add_init_script error: {e}")

    # ── Block tracker / quảng cáo, giữ Cloudflare đi qua ───────────────────
    _BLOCK_DOMAINS = (
        "google-analytics",
        "googletagmanager",
        "doubleclick",
        "facebook.net",
        "fbcdn.net",
        "hotjar",
    )
    _BLOCK_TYPES = ("media", "ping")

    async def _handle_route(route):
        req = route.request
        url = req.url.lower()
        rtype = req.resource_type

        if "cloudflare" in url:
            await route.continue_()
            return

        if any(d in url for d in _BLOCK_DOMAINS):
            await route.abort()
            return

        if rtype in _BLOCK_TYPES:
            await route.abort()
            return

        await route.continue_()

    try:
        await page.route("**/*", _handle_route)
    except Exception as e:
        logger.debug(f"⚠️ [{label}] Cannot setup route: {e}")


async def _close_unwanted_popups(page):
    """b) Đóng modal/popup/notification không mong muốn trước khi submit."""
    try:
        closed = await page.evaluate("""
            () => {
                const CLOSE_KEYWORDS = ['đóng', 'close', 'x', 'cancel', 'hủy', 'dismiss', 'got it', 'ok', 'thoát'];
                const SKIP_TEXT = ['xác thực', 'xac thuc', 'submit', 'kiểm tra', 'áp dụng', 'nhận'];
                const OVERLAY_SEL = [
                    '.modal', '[class*="modal" i]', '[class*="popup" i]',
                    '[class*="overlay" i]', '[class*="dialog" i]',
                    '[class*="notification" i]', '[class*="toast" i]',
                    '[class*="alert" i]:not(.alert-success):not(.alert-info)',
                    '[class*="banner" i]', '[class*="announcement" i]',
                ];
                let count = 0;
                for (const sel of OVERLAY_SEL) {
                    const els = [...document.querySelectorAll(sel)];
                    for (const el of els) {
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') continue;
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 || rect.height === 0) continue;
                        // Tìm nút đóng bên trong
                        const btns = [...el.querySelectorAll('button, [role="button"], a, span')];
                        for (const btn of btns) {
                            const txt = (btn.innerText || btn.textContent || btn.getAttribute('aria-label') || '').trim().toLowerCase();
                            if (SKIP_TEXT.some(s => txt.includes(s))) continue;
                            if (CLOSE_KEYWORDS.some(k => txt === k || txt.startsWith(k))) {
                                btn.click();
                                count++;
                                break;
                            }
                        }
                    }
                }
                return count;
            }
        """)
        if closed and closed > 0:
            logger.debug(f"🧹 Đóng {closed} popup không mong muốn")
            await asyncio.sleep(0.3)
    except Exception:
        pass


async def _wake_tab_for_submit(page):
    """Wake up tab before submitting."""
    try:
        await page.bring_to_front()
        await page.evaluate("""
            Object.defineProperty(document, 'visibilityState', {
                get: () => 'visible', configurable: true
            });
        """)
        await _close_unwanted_popups(page)
    except Exception:
        pass


async def auto_fill_username_on_startup(page, domain: str, username: str):
    """Fill username on page load với random delay."""
    try:
        # ✅ Random delay để giống người dùng thực
        await asyncio.sleep(random.uniform(0.5, 1.5))

        await scroll_to_input_fields(page)
        await asyncio.sleep(random.uniform(0.2, 0.5))  # Random scroll delay

        username_input, _ = await find_input_fields(page, cache_key=None)
        if not username_input:
            return False

        current_value = await get_input_value(username_input)

        if current_value.lower() == username.lower():
            return True

        if current_value == "":
            # ✅ Điền từ từ (giống người gõ) thay vì fill ngay
            for char in username:
                await username_input.type(char, delay=random.uniform(20, 80))  # 20-80ms giữa ký tự
                await asyncio.sleep(random.uniform(0.01, 0.05))

            logger.info(f"✅ [{domain}] Filled username: {username}")
            return True

        return False

    except Exception as e:
        logger.warning(f"⚠️ [{domain}] Cannot fill username: {e}")
        return False


async def _setup_one_domain_tab(
    item: dict, assigned_pages: set, assign_lock: asyncio.Lock
):
    """Setup one domain tab with timeout."""
    label = item.get("key", item["domain"])
    try:
        return await asyncio.wait_for(
            _setup_one_domain_tab_inner(item, assigned_pages, assign_lock),
            timeout=20.0,
        )
    except asyncio.TimeoutError:
        logger.warning(f"⏰ [{label}] Setup timeout 20s")
        return False
    except Exception as e:
        logger.error(f"❌ [{label}] Setup error: {e}")
        return False


async def _setup_one_domain_tab_inner(
    item: dict, assigned_pages: set, assign_lock: asyncio.Lock
):
    """Inner setup logic."""
    target_url = item["target_url"]
    domain = item["domain"]
    port = item["port"]
    accounts = item["accounts"]
    key = item.get("key", domain)

    # v7.5: Dùng 1 context chung "shared" → tất cả tab nằm trong 1 cửa sổ Chromium
    _first_user = (accounts[0]["username"] if accounts else None)
    if not _first_user:
        logger.error(f"❌ [{domain}] Không có account nào đặt cấu hình")
        return False
    context = await get_or_launch_browser_context("shared")
    page = None
    reason = ""

    async with assign_lock:
        for p in context.pages:
            try:
                if domain in p.url.lower() and p not in assigned_pages:
                    page = p
                    reason = "tab_existing"
                    assigned_pages.add(page)
                    break
            except Exception:
                pass

        if not page:
            if bool(getattr(Config, "AUTO_OPEN_MISSING_TABS", True)):
                page = await context.new_page()
                assigned_pages.add(page)
                reason = "tab_new"
            else:
                logger.error(f"❌ [{domain}] No tab available")
                return False

    if reason == "tab_new":
        await _setup_page_performance(page, label=domain)
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=10000)
            # ✅ DÒNG 925: Thêm 2 dòng
            await scroll_to_input_fields(page)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning(f"⚠️ [{domain}] Page load error (continuing): {e}")
    else:
        await _setup_page_performance(page, label=domain)
        await scroll_to_input_fields(page)
        await asyncio.sleep(0.5)

    bot_state.account_pages[key] = page
    bot_state.context_locks[key] = asyncio.Lock()
    bot_state.cf_verified[key] = False  # sẽ xác nhận True ở bước chờ xác minh sau preload
    bot_state.submission_count[key] = 0

    try:
        await page.bring_to_front()
    except Exception:
        pass

    logger.info(f"📂 [{key}] Tab đã mở — chờ xác minh ở bước tiếp theo")
    return True


async def wait_for_manual_verification_and_fill_accounts(account_targets: list):
    """
    Chờ người dùng tự tích/xác minh Turnstile thủ công trên TOÀN BỘ cửa sổ
    đã mở, sau đó mới tự động nhập "Tên Tài Khoản" cho từng tab.

    Không có gì ở đây cố "vượt" Cloudflare — chỉ poll xem widget Turnstile
    còn hiển thị trên trang hay không. Khi không còn (người dùng đã xác
    minh xong tay), bot mới được phép nhập tài khoản và coi tab đó là sẵn
    sàng nhận code. Log định kỳ để không bị hiểu lầm là treo (giống lỗi
    VERIFYING CHANNELS lần trước).
    """
    accounts_by_key = {item.get("key", item["domain"]): item["accounts"] for item in account_targets}
    pending = set(accounts_by_key.keys()) & set(bot_state.account_pages.keys())

    if not pending:
        logger.warning("⚠️ Không có tab nào để chờ xác minh")
        return

    logger.info("\n" + "=" * 70)
    logger.info(f"🔒 ĐANG CHỜ XÁC MINH THỦ CÔNG cho {len(pending)} cửa sổ...")
    logger.info("   Hãy tự tích/giải Turnstile trên từng tab. Bot sẽ tự nhập")
    logger.info("   tài khoản ngay sau khi mỗi tab xác minh xong, KHÔNG cần bấm gì thêm.")

    poll_interval = 3.0
    remind_every = 20.0
    elapsed = 0.0

    while pending:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        for key in list(pending):
            page = bot_state.account_pages.get(key)
            if not page or page.is_closed():
                continue
            try:
                cf_present = await is_cloudflare_present(page)
            except Exception:
                continue

            if not cf_present:
                accounts = accounts_by_key.get(key, [])
                # ✅ Lấy tài khoản HIỆN TẠI chưa dùng hôm nay (không cứng acc[0])
                next_acc = _get_next_available_account(key, accounts)
                fill_username = next_acc["username"] if next_acc else (accounts[0]["username"] if accounts else "")
                if fill_username:
                    await auto_fill_username_on_startup(page, key, fill_username)
                _, code_input = await find_input_fields(page)
                bot_state.cf_verified[key] = True
                pending.discard(key)
                if code_input:
                    logger.info(f"✅ [{key}] Đã xác minh xong — đã nhập tài khoản [{fill_username}], sẵn sàng nhận code")
                else:
                    logger.warning(f"⚠️ [{key}] Đã hết Turnstile nhưng không tìm thấy ô nhập code — kiểm tra lại tay")

        if pending and elapsed >= remind_every:
            elapsed = 0.0
            logger.info(f"⏳ Vẫn đang chờ xác minh thủ công: {sorted(pending)}")
            # Nhắc admin qua Telegram mỗi 20 giây
            await notify_admin(
                f"⏳ BOT đang chờ xác minh Cloudflare thủ công!\n"
                f"🌐 Các site cần xác minh: {', '.join(sorted(pending))}\n"
                f"👉 Mở cửa sổ Camoufox và click xác minh!"
            )

    logger.info("✅ TẤT CẢ CỬA SỔ ĐÃ XÁC MINH XONG — bot sẵn sàng nhận và submit code.")
    camoufox_minimize()  # Minimize sau khi xác minh xong — đợi code


# ── Dual-Tab Pool (2 tab song song, on-demand navigation) ──────────────────
TAB_POOL_SIZE = 1            # 1 tab duy nhất — mở khi có code, đóng sau submit

class TabPool:
    """Pool 2 tab Camoufox — mỗi submit lấy 1 tab rảnh, xong trả lại."""

    def __init__(self, size: int = 2):
        self.size      = size
        self._pages    = []          # list các page
        self._locks    = []          # asyncio.Lock riêng cho mỗi tab
        self._sem      = None        # Semaphore giới hạn đồng thời

    async def init(self):
        """Khởi tạo pool: mở `size` tab blank."""
        context  = await get_or_launch_browser_context("shared")
        self._sem = asyncio.Semaphore(self.size)

        # Dùng tab sẵn có của Camoufox trước
        existing = list(context.pages)

        for i in range(self.size):
            if i < len(existing):
                page = existing[i]
            else:
                page = await context.new_page()
            await _setup_page_performance(page, f"tab-{i}")
            # Cả 2 tab đều về Google lúc khởi động — không đen, không hiện trang MM88 sớm
            try:
                await page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=10000)
                label = "MM88-riêng (chờ 12:00-16:00)" if i == 0 else "shared"
                logger.info(f"  🌐 Tab-{i} [{label}] → google.com")
            except Exception:
                pass
            self._pages.append(page)
            self._locks.append(asyncio.Lock())
            logger.info(f"  🗂️ Tab-{i} sẵn sàng")

        logger.info(f"✅ TabPool {self.size} tab khởi tạo xong")

    async def acquire(self, domain: str = ""):
        """
        1 tab duy nhất — lazy init khi có code đầu tiên.
        Nếu tab đang bận thì chờ.
        """
        # Lazy init: mở Camoufox lần đầu khi có code thật
        if not self._pages:
            logger.info("🚀 [Lazy] Lần đầu có code — khởi động Camoufox...")
            await self.init()

        # Chờ tab rảnh
        lock = self._locks[0]
        max_wait = 60.0
        waited = 0.0
        while lock.locked():
            await asyncio.sleep(0.2)
            waited += 0.2
            if waited >= max_wait:
                logger.warning(f"TabPool: chờ tab-0 quá {max_wait}s cho [{domain}]")
                break

        page = self._pages[0]
        if page.is_closed():
            try:
                context = await get_or_launch_browser_context("shared")
                page = await context.new_page()
                await _setup_page_performance(page, "tab-0")
                self._pages[0] = page
            except Exception as e:
                logger.error(f"TabPool: không tạo lại tab-0: {e}")

        logger.debug(f"🗂️ TabPool: [{domain}] → Tab-0")
        return 0, self._pages[0], self._locks[0]

    def release(self):
        """Trả tab về pool — không cần release sem vì dùng lock riêng."""
        pass  # Lock tự release khi ra khỏi async with


_tab_pool: TabPool | None = None


async def get_shared_page():
    """Compat stub — trả tab-0 của pool (dùng ở nơi cần 1 page đơn)."""
    global _tab_pool
    if _tab_pool and _tab_pool._pages:
        return _tab_pool._pages[0]
    context = await get_or_launch_browser_context("shared")
    if context.pages:
        return context.pages[0]
    return await context.new_page()


async def preload_browsers_and_accounts():
    """
    Single-Tab On-Demand: không mở trước 8 tab.
    Chỉ khởi động Camoufox + 1 tab blank, đăng ký keys vào bot_state.
    Tab sẽ navigate đến đúng site khi có code cần submit.
    → Tiết kiệm RAM, không có tab thừa.
    """
    global _shared_page_lock
    bot_state._site_code_seen.clear()
    logger.info("🧹 Cleared runtime code cache")

    account_targets = build_unique_account_targets()
    if not account_targets:
        logger.error("❌ No channels configured")
        return

    # LAZY LAUNCH: không mở Camoufox ngay — chỉ tạo TabPool rỗng
    # Camoufox sẽ tự mở lần đầu khi có code cần submit
    global _tab_pool
    _tab_pool = TabPool(size=1)
    # Không gọi _tab_pool.init() ở đây — init() sẽ được gọi lần đầu trong acquire()

    # Đăng ký keys
    for item in account_targets:
        key = item.get("key", item["domain"])
        bot_state.context_locks[key]    = asyncio.Lock()
        bot_state.cf_verified[key]      = True
        bot_state.submission_count[key] = 0
        logger.info(f"  ✅ Đăng ký kênh: {key}")

    logger.info(f"✅ {len(account_targets)} kênh đăng ký xong — bot chờ code")
    logger.info("🤖 BOT RUNNING — Camoufox sẽ mở khi có code đầu tiên...")


# ============================================================
# CODE EXTRACTION & VALIDATION
# ============================================================


def validate_candidate(code: str, target_url: str, source: str = "normal"):
    """Validate code candidate."""
    try:
        return CodeValidator.validate_code(code, target_url, source=source)
    except TypeError:
        return CodeValidator.validate_code(code, target_url)


def get_filter_group_name(target_url: str) -> str:
    """Get filter group name for URL."""
    group_name, _ = CodeValidator.get_filter_group(target_url)
    return group_name


def unique_keep_order(items):
    """Remove duplicates while keeping order."""
    seen = set()
    result = []
    for item in items:
        clean = CodeValidator.clean_code(item)
        if not clean:
            continue
        upper = clean.upper()
        if upper not in seen:
            seen.add(upper)
            result.append(clean)
    return result


def remove_noise_from_text(text: str) -> str:
    """Remove URLs and noise from text."""
    cleaned = text or ""
    cleaned = re.sub(r"https?://\S+", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"www\.\S+", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b[a-zA-Z0-9.-]+\.(com|net|org|vn|app|info)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = cleaned.replace("：", ":").replace("|", " ").replace("•", " ")
    return cleaned


def clean_llwin_ocr_text(text: str) -> str:
    """
    LLwin OCR: xoá các cụm 'code bỏ số X', 'code bỏ chữ X' (và biến thể)
    mà Tesseract đọc ra từ chú thích trong ảnh.
    Ví dụ: 'R2T9D25Q  code bỏ số 2' → 'R2T9D25Q'
    """
    if not text:
        return text
    # Khớp: "code bỏ số <anything>", "code bỏ chữ <anything>", "CODE BO SO ..."
    # Có thể xuất hiện giữa dòng hoặc cuối dòng
    pattern = re.compile(
        r"code\s+b[oỏ]\s+(?:s[oố]\s*\S*|ch[uữ]\s*\S*)",
        re.IGNORECASE,
    )
    cleaned_lines = []
    for line in text.splitlines():
        line = pattern.sub("", line).strip()
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


# Anchor phrases báo hiệu codes đứng ngay sau — dùng cho NEW88
NEW88_CODE_ANCHORS = [
    "ANH EM NHANH TAY NHÉ",
    "ANH EM NHANH TAY NHE",
    "NHANH TAY NHÉ",
    "NHANH TAY NHE",
    "ANH EM NHANH TAY",
    "NEW88 TẶNG",
    "NEW88 TANG",
    "CODE FREE",
    "NHẬN CODE FREE",
    "NHAN CODE FREE",
]


def extract_new88_anchor_codes(text: str, target_url: str) -> list:
    """
    NEW88: Lấy tất cả token trông giống code nằm sau anchor phrase.
    Ví dụ:
        "NEW88 TẶNG CODE FREE , ANH EM NHANH TAY NHÉ!
         KnbJ5MdcDY  nhWeSPWhc4
         Qc78G2QhjX  XGPjYvzRwd ..."
    → Trả về tất cả token alphanumeric 8-16 ký tự phía sau anchor.
    Ưu tiên spoiler vẫn được gọi trước hàm này.
    """
    if not text:
        return []

    upper = text.upper()
    anchor_pos = -1
    for anchor in NEW88_CODE_ANCHORS:
        pos = upper.find(anchor.upper())
        if pos != -1:
            if anchor_pos == -1 or pos < anchor_pos:
                anchor_pos = pos

    if anchor_pos == -1:
        return []

    # Lấy phần text sau anchor
    after_anchor = text[anchor_pos:]

    # Extract mọi token có dạng code: chữ+số hoặc chữ+chữ mixed-case, 8-16 ký tự
    raw_tokens = re.findall(r"[A-Za-z0-9]{8,16}", after_anchor)

    codes = []
    for token in raw_tokens:
        # Phải có cả chữ lẫn số (loại bỏ từ thuần chữ như "ANH", "EM"...)
        has_letter = any(c.isalpha() for c in token)
        has_digit = any(c.isdigit() for c in token)
        if not (has_letter and has_digit):
            continue

        clean = CodeValidator.clean_code(token)
        try:
            v = CodeValidator.validate_code(clean, target_url=target_url, source="new88_anchor")
        except TypeError:
            v = CodeValidator.validate_code(clean, target_url)

        if v["valid"]:
            codes.append(v["clean_code"])
            logger.info(f"🎯 [NEW88-ANCHOR] Code: {v['clean_code']}")

    return list(dict.fromkeys(codes))  # dedup, giữ thứ tự


def line_has_code_marker(line: str) -> bool:
    """Check if line has code marker."""
    upper = line.upper()
    markers = [
        "NHẬN CODE NGAY",
        "NHAN CODE NGAY",
        "NHẬN CODE",
        "NHAN CODE",
        "NHẬP CODE",
        "NHAP CODE",
        "PHÁT CODE",
        "PHAT CODE",
        "CODE FREE",
        "FREE CODE",
        "GIFT CODE",
        "GIFTCODE",
        "TẶNG CODE",
        "TANG CODE",
    ]
    return any(m in upper for m in markers)


def line_is_noise(line: str) -> bool:
    """Check if line is noise."""
    upper = line.upper().strip()
    if not upper:
        return True
    noise_keywords = [
        "HTTP",
        "WWW",
        ".COM",
        "FACEBOOK",
        "TELEGRAM",
        "TIKTOK",
        "ZALO",
        "CSKH",
        "BOT",
        "CHECK LINK",
        "LINK",
    ]
    return any(kw in upper for kw in noise_keywords)


def extract_tokens_from_line(line: str):
    """Extract code tokens from line."""
    special_chars = re.escape(getattr(Config, "SPECIAL_CODE_CHARS_30", ""))
    min_len = getattr(Config, "CODE_MIN_LENGTH", 6)
    max_len = getattr(Config, "CODE_MAX_LENGTH", 15)
    max_raw_len = max_len + 30

    pattern = rf"[A-Za-z0-9{special_chars}]{{{min_len},{max_raw_len}}}"
    tokens = []

    for candidate in re.findall(pattern, line or ""):
        clean = CodeValidator.clean_code(candidate)
        if min_len <= len(clean) <= max_len:
            tokens.append(candidate)

    return tokens


def extract_spoiler_codes(event, target_url: str):
    """Extract codes from spoiler text."""
    codes = []
    if not event.message.entities:
        return codes

    try:
        for entity, entity_text in event.message.get_entities_text():
            if not isinstance(entity, MessageEntitySpoiler):
                continue

            spoiler_text = (entity_text or "").strip()
            if not spoiler_text:
                continue

            spoiler_lines = (
                spoiler_text.splitlines() if "\n" in spoiler_text else [spoiler_text]
            )

            for spoiler_line in spoiler_lines:
                spoiler_line = spoiler_line.strip()
                if not spoiler_line:
                    continue

                tokens = extract_tokens_from_line(spoiler_line) or [spoiler_line]
                for token in tokens:
                    validation = validate_candidate(token, target_url, source="spoiler")
                    if validation["valid"]:
                        codes.append(validation["clean_code"])
                        logger.info(f"🔒 Spoiler code: {validation['clean_code']}")

    except Exception as e:
        logger.warning(f"⚠️ Error reading spoiler: {e}")

    return unique_keep_order(codes)


def extract_marker_near_codes(text: str, target_url: str):
    """Extract codes near markers."""
    cleaned_text = remove_noise_from_text(text)
    lines = [line.strip() for line in cleaned_text.splitlines()]
    codes = []

    for index, line in enumerate(lines):
        if not line_has_code_marker(line):
            continue

        scan_lines = [line] if line else []
        for offset in range(1, 9):
            if index + offset < len(lines):
                scan_lines.append(lines[index + offset])

        for scan_line in scan_lines:
            if line_is_noise(scan_line):
                continue

            for token in extract_tokens_from_line(scan_line):
                clean = CodeValidator.clean_code(token)
                validation = validate_candidate(clean, target_url, source="marker")
                if validation["valid"]:
                    codes.append(validation["clean_code"])
                    logger.info(f"🎯 Marker code: {validation['clean_code']}")

    return unique_keep_order(codes)


def extract_codes_by_regex(text: str, site_type: str = "qq88") -> list:
    """Extract codes by regex pattern."""
    if not text:
        return []

    codes = []

    if site_type == "qq88":
        QQ88_BLACKLIST = {
            "QQ88",
            "CODE",
            "DANGNHAP",
            "GAMEBAI",
            "NOHU",
            "CASINO",
            "REVIEWPHIM",
            "TINTUC",
            "KHUYENMAI",
            "GIFTCODE",
            "FREECODE",
            "CAMERA",
            "TROLL",
            "BONGDA",
            "THETHAO",
            "MINIGAME",
        }
        for match in re.findall(r"[a-zA-Z0-9]{6,15}", text):
            if any(kw in match.upper() for kw in QQ88_BLACKLIST):
                continue
            has_letter = any(c.isalpha() for c in match)
            has_digit = any(c.isdigit() for c in match)
            has_lower = any(c.islower() for c in match)
            has_upper_c = any(c.isupper() for c in match)
            if has_letter and (has_digit or (has_lower and has_upper_c)):
                codes.append(match)

    # LLwin: regex cũ bị loại vì nó bắt đúng dòng BẪY (K6$OSX, R%UAZO).
    # Dùng extract_llwin_code12_lines() thay thế.

    return list(dict.fromkeys(codes))


def extract_llwin_code12_lines(text: str) -> list:
    """
    Trích code từ định dạng riêng của LLwin:

        CODE FREE : FX74#3 VS J$4Z7D   ← dòng BẪY  (có $ # → bỏ qua)
        CODE 1: KT5_H                   ← code THẬT
        CODE 2: KT2_C                   ← code THẬT

    Quy tắc:
      • Chỉ đọc dòng có pattern "CODE 1:" hoặc "CODE 2:"
      • Bỏ nếu giá trị chứa ký tự bẫy ($  %  #  @  !  ^  &  *  ~)
      • Bỏ nếu giá trị chỉ là "KT" đơn thuần (bẫy không có suffix)
      • Nhận code 4-15 ký tự [A-Z0-9_] có cả chữ lẫn chữ-số/gạch-dưới
      • Hoạt động cho cả text thường lẫn text trong spoiler
        (Telethon đưa toàn bộ nội dung kể cả spoiler vào .text)
    """
    DECOY_CHARS = set('$%#@!^&*~|\\<>=+')
    BLACKLIST   = {'KT', 'CODE', 'FREE', 'VIP', 'GAME', 'LINK', 'LLWIN',
                   'MB', 'PC', 'VS', 'NHAP', 'NHAN'}
    codes = []

    for line in (text or "").splitlines():
        line = line.strip()
        m = re.match(r'CODE\s*[12]\s*:\s*(.+)', line, re.IGNORECASE)
        if not m:
            continue

        raw_value = m.group(1).strip()

        # Dòng bẫy: chứa ký tự đặc biệt kiểu K6$OSX hoặc R%UAZO
        if any(c in DECOY_CHARS for c in raw_value):
            logger.debug(f"[LLWIN-CODE12] Bỏ bẫy đặc biệt: {raw_value[:40]}")
            continue

        # Lấy token [chữ/số/gạch-dưới] dài 4-15 ký tự
        tokens = re.findall(r'[A-Za-z0-9_]{4,15}', raw_value)
        for token in tokens:
            upper = token.upper()

            if upper in BLACKLIST:
                logger.debug(f"[LLWIN-CODE12] Bỏ blacklist: {upper}")
                continue

            # Phải có cả chữ cái lẫn thứ không phải chữ (số hoặc gạch dưới)
            has_alpha    = any(c.isalpha() for c in token)
            has_nonalpha = any(not c.isalpha() for c in token)
            if not (has_alpha and has_nonalpha):
                logger.debug(f"[LLWIN-CODE12] Bỏ alpha-only/digit-only: {upper}")
                continue

            codes.append(upper)
            logger.info(f"✅ [LLWIN-CODE12] Code: {upper}")

    return list(dict.fromkeys(codes))


def extract_codes_from_message(event, raw_text: str, target_url: str):
    """Extract all codes from message."""
    codes = []
    group_name = get_filter_group_name(target_url)

    logger.debug(f"[EXTRACT] group={group_name} | url={target_url}")

    # ── 1) Spoiler ưu tiên cao nhất ─────────────────────────────────────────
    spoiler_codes = extract_spoiler_codes(event, target_url)
    if spoiler_codes:
        logger.warning(f"🎯 [SPOILER] Found {len(spoiler_codes)} codes: {spoiler_codes}")
        return spoiler_codes
    else:
        logger.debug(f"   [SPOILER] No spoiler codes")

    # ── 2) NEW88 anchor: lấy code sau "ANH EM NHANH TAY NHÉ" / "CODE FREE" ─
    if group_name == "new88":
        anchor_codes = extract_new88_anchor_codes(raw_text, target_url)
        if anchor_codes:
            logger.warning(f"🎯 [NEW88-ANCHOR] Found: {anchor_codes}")
            return anchor_codes

    # ✅ UY88 & QQ88: ưu tiên spoiler, nếu không có spoiler thì vẫn cho phép
    # lấy code đứng cạnh marker rõ ràng (FREE CODE:, GIFT CODE:, CODE:, ...)
    # để tránh bỏ lỡ code thật như "FREE CODE: qB9eD9MUNJ" trong caption ảnh.
    if group_name == "qq88":
        caption_text = (event.message.message or raw_text or "").strip().lower()
        has_media = bool(event.media)
        has_raw_text = bool(raw_text.strip())

        QQ88_CODE_TRIGGERS = [
            "tangquaqq88.com", "link nhập code", "link nhap code", "tangquaqq88",
            "nhập code", "nhap code",
            "free code", "freecode", "gift code", "giftcode",
            "tặng code", "tang code", "mã code", "ma code",
        ]
        QQ88_AD_SKIP = [
            "khuyến mãi", "khuyen mai", "giảm giá", "sale", "promo", "quảng cáo", "nạp tiền"
        ]

        if has_raw_text:
            logger.info("✅ [QQ88] Text/spoiler → xử lý ngay")
        elif has_media:
            if any(kw in caption_text for kw in QQ88_AD_SKIP):
                logger.info(
                    f"⏭️ [QQ88] Ảnh quảng cáo → bỏ qua (caption: {caption_text[:80]})"
                )
                return []
            if any(kw in caption_text for kw in QQ88_CODE_TRIGGERS):
                logger.info(
                    f"✅ [QQ88] Caption có trigger code → OCR (caption: {caption_text[:80]})"
                )
            else:
                logger.info(
                    f"⏭️ [QQ88] Caption không có trigger → bỏ qua (caption: {caption_text[:80]})"
                )
                return []
        else:
            logger.info("⏭️ [QQ88] Không có text lẫn ảnh → bỏ qua")
            return []

    # Try marker
    marker_codes = extract_marker_near_codes(raw_text, target_url)
    if marker_codes:
        logger.warning(f"🎯 [MARKER] Found {len(marker_codes)} codes: {marker_codes}")
        return marker_codes
    else:
        logger.debug(f"   [MARKER] No marker codes")

    # ── LLwin: trích code từ dòng "CODE 1: KTx_y" / "CODE 2: KTx_y" ────────
    # Regex cũ (LLWIN_SEP) bắt đúng dòng BẪY (K6$OSX, R%UAZO) nên đã bị
    # loại bỏ. extract_llwin_code12_lines() chỉ đọc "CODE [12]:" và lọc decoy.
    if group_name == "llwin":
        code12 = extract_llwin_code12_lines(raw_text)
        if code12:
            logger.warning(f"🎯 [LLWIN-CODE12] Found: {code12}")
            return code12
        logger.debug("[LLWIN-CODE12] Không tìm thấy CODE 1/2 format")

    # ✅ QQ88: fallback regex chỉ chạy khi có trigger keyword rõ ràng
    # Xóa URL trước để tránh lấy nhầm ID trong link t.me/addlist/JTL2P_bKxRszZjA1
    if group_name == "qq88":
        _qq88_triggers = [
            "free code", "freecode", "gift code", "giftcode",
            "tặng code", "tang code", "mã code", "ma code",
            "nhập code", "nhap code", "tangquaqq88",
        ]
        _text_lower = raw_text.lower()
        if any(kw in _text_lower for kw in _qq88_triggers):
            # Xóa URL và t.me links trước khi regex
            _clean = re.sub(r'https?://\S+', '', raw_text)
            _clean = re.sub(r't\.me/\S+', '', _clean)
            regex_raw = extract_codes_by_regex(_clean, site_type="qq88")
            regex_codes = []
            for raw in regex_raw:
                v = validate_candidate(raw, target_url, source="regex")
                if v["valid"]:
                    regex_codes.append(v["clean_code"])
            if regex_codes:
                logger.info(f"🎯 [QQ88-REGEX] Fallback found: {regex_codes}")
                return list(dict.fromkeys(regex_codes))
        else:
            logger.debug("[QQ88-REGEX] Không có trigger keyword → bỏ qua")

    logger.debug(f"[EXTRACT] No codes found using any method")
    return codes


# ============================================================
# SUBMIT CODE
# ============================================================

REACT_FILL_JS = """
    ([el, val]) => {
        const proto = el.tagName === 'TEXTAREA'
            ? window.HTMLTextAreaElement.prototype
            : window.HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
        el.focus();
        setter.call(el, '');
        setter.call(el, val);
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
    }
"""


async def _reset_page_after_success(
    page, key: str, target_url: str, domain: str, user: str
):
    """
    Reset page sau khi submit thành công.
    - Đánh dấu tài khoản đã dùng hôm nay
    - Xoay sang tài khoản kế tiếp và điền vào form (1 tab duy nhất)
    - Nếu hết tài khoản → đóng tab (không còn cần thiết trong ngày)
    - MM88: mỗi tab gắn với 1 account → đóng tab sau khi account dùng xong
    """
    # 1) Đánh dấu account đã dùng xong hôm nay
    _mark_account_done_today(key, user)

    try:
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

        try:
            await page.evaluate("""
                () => {
                    const closeSelectors = [
                        '.swal2-close', '.swal2-confirm',
                        '[aria-label="Close"]', '[aria-label="close"]',
                        'button[class*="close" i]',
                        '.modal [class*="close" i]',
                    ];
                    for (const sel of closeSelectors) {
                        const btn = document.querySelector(sel);
                        if (btn) { btn.click(); return true; }
                    }
                    return false;
                }
            """)
        except Exception:
            pass

        await asyncio.sleep(0.1)

        # 2) Tìm tài khoản kế tiếp cho kênh này
        # Lấy danh sách accounts từ CHANNEL_CONFIG theo domain
        next_user = None
        all_accounts_for_domain = []

        if domain != "mm88code.com":
            # Kênh thông thường: 1 tab, xoay account
            for cfg in Config.CHANNEL_CONFIG.values():
                if normalize_domain(cfg["url"]) == domain:
                    all_accounts_for_domain = sorted(
                        cfg.get("accounts", []), key=lambda a: a.get("priority", 999)
                    )
                    break
            next_acc = _get_next_available_account(key, all_accounts_for_domain)
            next_user = next_acc["username"] if next_acc else None
        else:
            # MM88: tab gắn với 1 account cụ thể → không xoay trên tab này
            next_user = None

        if next_user:
            # Reload trang và điền tài khoản mới
            await page.goto(target_url, wait_until="domcontentloaded", timeout=10000)
            await asyncio.sleep(0.3)
            _invalidate_input_cache(key)
            bot_state._page_urls[key] = page.url

            # Điền username mới vào form
            await auto_fill_username_on_startup(page, key, next_user)
            logger.info(
                f"🔄 [{domain}|{user}] ✅ Thành công → Xoay sang tài khoản tiếp theo: [{next_user}]"
            )
        else:
            # Hết tài khoản cho hôm nay → đóng tab này
            logger.info(
                f"🔚 [{domain}|{user}] Đã dùng hết tài khoản hôm nay → đóng tab"
            )
            try:
                await page.close()
            except Exception:
                pass
            # Xóa khỏi state
            bot_state.account_pages.pop(key, None)
            bot_state.context_locks.pop(key, None)
            bot_state._input_cache.pop(key, None)
            bot_state._page_urls.pop(key, None)
            bot_state.cf_verified.pop(key, None)

        return True
    except Exception as e:
        logger.warning(f"⚠️ [{domain}|{user}] Lỗi reset page: {e}")
        return False


async def submit_code_safe(user: str, code: str, target_url: str, systems: dict):
    """Submit code to target URL."""
    start_time = time.time()
    db = systems["db"]
    perf_mon = systems["performance_monitor"]
    domain = normalize_domain(target_url)

    logger.warning(f"🚀 SUBMIT START | user={user} | code={code} | domain={domain}")

    if domain == "mm88code.com":
        key = f"{domain}|{user}"
    else:
        key = domain

    if key not in bot_state.context_locks:
        logger.warning(f"⏭️ [{user}|{domain}] No tab")
        return {"success": False, "message": "No tab"}

    if _tab_pool is None:
        return {"success": False, "message": "TabPool chưa khởi tạo"}

    # Lấy tab phù hợp: MM88 → Tab-0, còn lại → Tab-1
    tab_idx, page, tab_lock = await _tab_pool.acquire(domain=domain)
    try:
      async with tab_lock:
        # Cập nhật page hiện tại cho key
        bot_state.account_pages[key] = page  # cập nhật page thật sau lazy init

        # ── On-Demand Navigation ────────────────────────────────────────────
        if page.is_closed():
            context = await get_or_launch_browser_context("shared")
            page = await context.new_page()
            await _setup_page_performance(page, domain)
            _tab_pool._pages[tab_idx] = page

        try:
            page_url = page.url
        except Exception:
            page_url = ""

        need_nav = (not page_url or "about:blank" in page_url or "google.com" in page_url or "Đang chờ" in page_url
                    or domain not in page_url.lower())
        if need_nav:
            logger.info(f"🌐 [Tab-{tab_idx}|{domain}] Điều hướng tới {target_url}")
            camoufox_restore()
            try:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=12000)
                await scroll_to_input_fields(page)
                await asyncio.sleep(0.5)
                _invalidate_input_cache(key)
            except Exception as e:
                logger.error(f"❌ [{domain}] Goto failed: {e}")
                _tab_pool.release()
                return {"success": False, "message": "Goto failed"}

            await _wake_tab_for_submit(page)
            camoufox_restore()  # Hiện cửa sổ lên khi bắt đầu submit

            # --- Check for Cloudflare/Turnstile presence and do NOT auto-bypass ---
            if await is_cloudflare_present(page):
                logger.warning(f"⚠️ [{domain}] Cloudflare challenge detected — cần xác minh thủ công")
                try:
                    await page.bring_to_front()
                except Exception:
                    pass
                # Gửi thông báo Telegram về cho admin
                await notify_admin(
                    f"⚠️ CLOUDFLARE chặn!\n"
                    f"🌐 Site: {domain}\n"
                    f"👤 Tài khoản: {user}\n"
                    f"🔑 Code đang submit: {code}\n"
                    f"👉 Mở cửa sổ Camoufox và xác minh thủ công!"
                )
                bot_state.cf_verified[key] = False
                return {"success": False, "message": "Cloudflare challenge present"}

            username_input, code_input = await find_input_fields(page, cache_key=key)

            if not code_input:
                await asyncio.sleep(0.05)
                _invalidate_input_cache(key)
                username_input, code_input = await find_input_fields(
                    page, cache_key=key
                )

            if not code_input:
                logger.warning(f"❌ [{user}|{domain}] No code input")
                return {"success": False, "message": "No code input"}

            await scroll_to_input_fields(page)
            await asyncio.sleep(0.3)  # chờ JS render sau scroll

            try:
                if username_input:
                    await page.evaluate(REACT_FILL_JS, [username_input, user])
                await page.evaluate(REACT_FILL_JS, [code_input, code])
            except Exception as e:
                _invalidate_input_cache(key)
                username_input, code_input = await find_input_fields(
                    page, cache_key=key
                )
                if code_input:
                    try:
                        if username_input:
                            await page.evaluate(REACT_FILL_JS, [username_input, user])
                        await page.evaluate(REACT_FILL_JS, [code_input, code])
                    except Exception as e2:
                        logger.warning(f"❌ [{user}|{domain}] Fill error: {e2}")
                        return {"success": False, "message": str(e2)}
                else:
                    return {"success": False, "message": f"Fill error: {e}"}

            try:
                await page.bring_to_front()
            except Exception:
                pass

            clicked = await click_submit_fast(page, domain=domain)
            if not clicked:
                logger.warning(f"⚠️ [{user}|{domain}] Submit not clicked")

            click_elapsed = time.time() - start_time
            logger.info(f"🚀 [{user}] SUBMIT {code} ({click_elapsed:.2f}s)")

            # Bước 2: Poll result (8s)
            result_text = ""
            poll_deadline = time.time() + 12.0
            while time.time() < poll_deadline:
                try:
                    candidate = await detect_result_text(page)
                    if candidate and len(candidate.strip()) >= 5:
                        result_text = candidate
                        break
                    if candidate and len(candidate.strip()) > len(result_text.strip()):
                        result_text = candidate
                except Exception:
                    pass
                await asyncio.sleep(0.2)

            elapsed = time.time() - start_time
            result_upper = result_text.upper()

            SUCCESS_KW = [
                "THÀNH CÔNG", "THANH CONG", "SUCCESS", "CỘNG", "CONG",
                "OK", "COMPLETED", "TẶNG", "TANG", "ĐIỂM", "DIEM",
                "NHẬN", "NHAN", "RECEIVED", "ADDED", "AWARDED",
                "CONGRATULATIONS", "APPROVED", "ACCEPTED",
            ]
            FAILED_KW = [
                "SAI", "LỖI", "LOI",
                "ĐÃ SỬ", "DA SU", "ĐÃ DÙNG",
                "FAILED", "ERROR", "INVALID",
                "KHÔNG ĐÚNG", "KHÔNG TỒN TẠI", "KHÔNG HỢP LỆ",
                "HẾT HẠN", "ĐÃ HẾT", "EXPIRED",
                "NOT FOUND", "NOT EXIST", "KHÔNG TÌM THẤY",
                "CODE NOT USED", "CODE_NOT_USED",
                "THAT BAI", "THẤT BẠI",
                "REJECTED", "DECLINED",
            ]
            TOO_MANY_KW = [
                "TOO MANY",
                "RATE LIMIT",
                "QUÁ NHIỀU",
                "429",
                "THÊM SAU",
                "THỬ LẠI SAU",
            ]
            POINT_KW = ["ĐIỂM", "XU", "COIN", "POINT"]

            is_success = any(kw in result_upper for kw in SUCCESS_KW)
            is_failed = any(kw in result_upper for kw in FAILED_KW)
            has_points = any(kw in result_upper for kw in POINT_KW)
            # c) Too Many Requests → backoff tự động
            is_rate_limited = any(kw in result_upper for kw in TOO_MANY_KW)
            if is_rate_limited:
                backoff_delay = (
                    float(getattr(Config, "MIN_DELAY_BETWEEN_SUBMITS", 0.8)) * 5
                )
                logger.warning(
                    f"🚫 [{user}|{domain}] Too Many Requests — backoff {backoff_delay:.1f}s"
                )
                await asyncio.sleep(backoff_delay)
                return {"success": False, "message": f"RateLimit:{result_text[:60]}"}

            if is_success and not is_failed:
                logger.info(
                    f"✅ [{user}] SUCCESS ({elapsed:.2f}s) — {result_text[:60]}"
                )
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    db.record_submission,
                    code,
                    user,
                    target_url,
                    "SUCCESS",
                    result_text[:100],
                )
                bot_state.submission_count[key] = (
                    bot_state.submission_count.get(key, 0) + 1
                )
                perf_mon.record_task("submit_code", elapsed, True)
                append_code_history(
                    event_type="RESULT",
                    code=code,
                    target_url=target_url,
                    account=user,
                    status="SUCCESS",
                    submit_elapsed=elapsed,
                    message=result_text[:100],
                )
                bot_state._tab_fail_count[key] = (
                    0  # g) reset fail counter khi thành công
                )
                await _reset_page_after_success(page, key, target_url, domain, user)
                try:
                    await page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=8000)
                except Exception:
                    pass
                _tab_pool.release()
                await close_camoufox_after_submit()
                return {
                    "success": True,
                    "has_points": has_points,
                    "message": result_text[:100],
                }

            if len(result_text.strip()) < 3:
                screenshot = await take_result_screenshot(
                    page, user, code, target_url, "UNKNOWN"
                )
                logger.warning(f"⚠️ [{user}] NO RESULT after {elapsed:.2f}s")
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    db.record_submission,
                    code,
                    user,
                    target_url,
                    "UNKNOWN",
                    "No popup",
                )
                perf_mon.record_task("submit_code", elapsed, False)
                append_code_history(
                    event_type="RESULT",
                    code=code,
                    target_url=target_url,
                    account=user,
                    status="UNKNOWN",
                    submit_elapsed=elapsed,
                    message="No popup",
                    screenshot=screenshot,
                )
                # g) Tăng fail counter, reload tab nếu vượt ngưỡng
                bot_state._tab_fail_count[key] = (
                    bot_state._tab_fail_count.get(key, 0) + 1
                )
                fail_count = bot_state._tab_fail_count[key]
                threshold = bot_state._TAB_FAIL_THRESHOLD
                logger.debug(f"⚠️ [{domain}] Fail count: {fail_count}/{threshold}")
                if fail_count >= threshold:
                    logger.warning(
                        f"🔄 [{domain}] {fail_count} lần thất bại liên tiếp → reload tab"
                    )
                    try:
                        await page.goto(
                            target_url, wait_until="domcontentloaded", timeout=10000
                        )
                        _invalidate_input_cache(key)
                        bot_state._tab_fail_count[key] = 0
                        logger.info(
                            f"✅ [{domain}] Tab reloaded sau {fail_count} lần thất bại"
                        )
                    except Exception as reload_err:
                        logger.error(f"❌ [{domain}] Reload thất bại: {reload_err}")
                _tab_pool.release()
                await close_camoufox_after_submit()
                return {"success": False, "message": "No popup"}

            screenshot = await take_result_screenshot(
                page, user, code, target_url, "FAILED"
            )
            logger.warning(f"❌ [{user}] FAILED ({elapsed:.2f}s) — {result_text[:60]}")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                db.record_submission,
                code,
                user,
                target_url,
                "FAILED",
                result_text[:100],
            )
            perf_mon.record_task("submit_code", elapsed, False)
            append_code_history(
                event_type="RESULT",
                code=code,
                target_url=target_url,
                account=user,
                status="FAILED",
                submit_elapsed=elapsed,
                message=result_text[:100],
                screenshot=screenshot,
            )
            return {"success": False, "message": result_text[:100]}

    except Exception as e:
        elapsed = time.time() - start_time
        err_str = str(e)
        # a) Xử lý mất kết nối CDP / Playwright TargetClosedError
        if (
            "Target page, context or browser has been closed" in err_str
            or "TargetClosedError" in type(e).__name__
        ):
            logger.warning(f"🔌 [{domain}] CDP mất kết nối, thử reconnect page...")
            try:
                port = None
                # Sửa lỗi NameError: tìm port dựa trên user trong cấu hình CDP_CONNECTIONS
                for p, users_list in getattr(Config, "CDP_CONNECTIONS", {}).items():
                    try:
                        if user in users_list:
                            port = int(p)
                            break
                    except Exception:
                        continue
                if port and port in bot_state.connected_browsers:
                    browser = bot_state.connected_browsers[port]
                    context = browser.contexts[0] if browser.contexts else None
                    if context:
                        new_page = await context.new_page()
                        bot_state.account_pages[key] = new_page
                        await _setup_page_performance(new_page, domain)
                        await new_page.goto(
                            target_url, wait_until="domcontentloaded", timeout=10000
                        )
                        _invalidate_input_cache(key)
                        logger.info(f"✅ [{domain}] Reconnect CDP thành công")
            except Exception as re_err:
                logger.error(f"❌ [{domain}] Reconnect CDP thất bại: {re_err}")
        logger.error(f"❌ [{user}] Submit error: {e}\n{traceback.format_exc()}")
        perf_mon.record_task("submit_code", elapsed, False)
        append_code_history(
            event_type="ERROR",
            code=code,
            target_url=target_url,
            account=user,
            status="ERROR",
            submit_elapsed=elapsed,
            message=str(e),
        )
        return {"success": False, "message": str(e)}


async def submit_code_with_delay(user: str, code: str, target_url: str, systems: dict):
    """Submit with min delay after semaphore released.

    ✅ Dùng semaphore RIÊNG theo domain → các site khác nhau (QQ88, NEW88, UY88...)
    chạy SONG SONG hoàn toàn, không phải xếp hàng chờ chung 1 semaphore global.
    Tránh tình trạng delay 600s khi nhiều tin đến cùng lúc từ nhiều kênh khác nhau.
    """
    domain = normalize_domain(target_url)
    sem = get_domain_semaphore(domain)
    result = {
        "success": False,
        "message": "Not started",
    }  # init mặc định tránh UnboundLocalError
    async with sem:
        try:
            result = await asyncio.wait_for(
                submit_code_safe(user, code, target_url, systems),
                timeout=25.0,
            )
        except asyncio.TimeoutError:
            logger.warning(f"⏰ [{user}] Submit timeout 25s")
            result = {"success": False, "message": "Timeout 25s"}
        except Exception as e:
            logger.error(f"❌ [{user}] submit_code_with_delay error: {e}")
            result = {"success": False, "message": str(e)}

    delay = float(getattr(Config, "MIN_DELAY_BETWEEN_SUBMITS", 0.5))
    if delay > 0:
        await asyncio.sleep(delay)

    return result


def track_submit_task(task: asyncio.Task, label: str = ""):
    """Track active submit task."""
    _active_submit_tasks.add(task)

    def _done(t: asyncio.Task):
        _active_submit_tasks.discard(t)
        try:
            result = t.result()
            if isinstance(result, dict):
                ok = "✅" if result.get("success") else "⚠️"
                logger.info(f"{ok} [TASK] {label} | {result.get('message', '')[:60]}")
        except asyncio.CancelledError:
            logger.debug(f"🛑 [TASK CANCELLED] {label}")
        except Exception as e:
            logger.error(f"❌ [TASK ERROR] {label}: {e}")

    task.add_done_callback(_done)
    return task


async def _submit_sequential_for_channel(
    codes: list,
    available_accounts: list,
    target_url: str,
    channel_name: str,
    domain: str,
):
    """
    Submit code cho kênh với 1 tab duy nhất.

    LOGIC MỚI (SINGLE-WINDOW):
    - Chỉ submit cho tài khoản ĐANG HOẠT ĐỘNG (chưa dùng hôm nay) trên tab duy nhất
    - Sau khi thành công, _reset_page_after_success() tự xoay sang tài khoản kế
    - Không vòng qua toàn bộ accounts trong 1 lần submit (tránh mở nhiều cửa sổ)
    """
    if not codes:
        return

    selected_code = select_random_code(codes)
    logger.info(f"🎲 [{domain}] Code: {selected_code} (from {len(codes)})")

    # Lấy tài khoản hiện tại đang active (chưa dùng hôm nay)
    current_acc = _get_next_available_account(domain, available_accounts)
    if current_acc is None:
        logger.info(f"✅ [{domain}] Tất cả tài khoản đã nhập xong hôm nay → bỏ qua")
        return

    user = current_acc["username"]
    max_retries = getattr(Config, "MAX_RETRIES_PER_ACCOUNT", 2)
    retry_on_timeout = getattr(Config, "RETRY_ON_TIMEOUT", True)

    logger.info(f"🔄 [{domain}] Submit code cho tài khoản hiện tại: [{user}]")

    for attempt in range(1, max_retries + 1):
        result = await submit_code_with_delay(user, selected_code, target_url, _systems)

        success = result.get("success", False) if result else False
        has_points = result.get("has_points", False) if result else False
        msg = (result.get("message", "") if result else "No result")[:80]

        if success and has_points:
            logger.info(f"✅ [{domain}|{user}] SUCCESS+POINTS ✨ Done!")
            append_code_history(
                event_type="FINAL_RESULT",
                code=selected_code,
                target_url=target_url,
                account=user,
                status="SUCCESS_POINTS",
                message="Code thành công với điểm/xu",
            )
            return

        if success and not has_points:
            logger.warning(
                f"⚠️ [{domain}|{user}] Code OK nhưng KHÔNG có điểm → DỪNG"
            )
            append_code_history(
                event_type="FINAL_RESULT",
                code=selected_code,
                target_url=target_url,
                account=user,
                status="SUCCESS_NO_POINTS",
                message="Code đúng nhưng không điểm",
            )
            return

        if success is False and any(kw in msg.upper() for kw in [
            "INVALID", "ALREADY USED", "EXPIRED", "NOT FOUND",
            "SAI MÃ", "MÃ SAI", "ĐÃ DÙNG", "HẾT HẠN",
            "THAT BAI", "CODE SAI",
        ]):
            logger.warning(f"❌ [{domain}|{user}] Code chắc chắn sai/hết hạn — dừng")
            append_code_history(
                event_type="SUBMIT_ATTEMPT",
                code=selected_code,
                target_url=target_url,
                account=user,
                status="FAILED",
                message=msg,
            )
            return  # Không chuyển sang acc khác, chờ code tiếp theo

        # Timeout / no popup
        if retry_on_timeout and attempt < max_retries:
            logger.info(
                f"🔄 [{domain}|{user}] Retry {attempt}/{max_retries} | "
                f"msg={msg[:40]} | chờ 2s..."
            )
            await asyncio.sleep(2)
        else:
            logger.warning(
                f"⏰ [{domain}|{user}] Hết {attempt} lần retry | msg={msg[:40]}"
            )
            append_code_history(
                event_type="FINAL_RESULT",
                code=selected_code,
                target_url=target_url,
                account=user,
                status="NO_RESULT",
                message=f"Timeout sau {attempt} lần thử",
            )
            return


async def _submit_one_account(account: dict, code: str, target_url: str, domain: str):
    """Submit 1 code cho 1 account (MM88 parallel)."""
    user = account["username"]
    logger.info(f"🔄 [{domain}|{user}] Submit code: {code}")

    result = await submit_code_with_delay(user, code, target_url, _systems)

    success = result.get("success", False) if result else False
    has_points = result.get("has_points", False) if result else False
    msg = (result.get("message", "") if result else "No result")[:80]

    if success and has_points:
        status = "SUCCESS_POINTS"
        logger.info(f"✅ [{domain}|{user}] SUCCESS+POINTS ✨")
    elif success and not has_points:
        status = "SUCCESS_NO_POINTS"
        logger.warning(f"⚠️ [{domain}|{user}] Code OK nhưng KHÔNG có điểm")
    elif success is False and any(kw in msg.upper() for kw in [
        "INVALID", "ALREADY USED", "EXPIRED", "NOT FOUND",
        "SAI MÃ", "MÃ SAI", "ĐÃ DÙNG", "HẾT HẠN",
    ]):
        status = "FAILED"
        logger.warning(f"❌ [{domain}|{user}] Code sai/hết hạn: {msg}")
    else:
        status = "NO_RESULT"
        logger.warning(f"⏰ [{domain}|{user}] TIMEOUT hoặc NO POPUP")

    append_code_history(
        event_type="FINAL_RESULT",
        code=code,
        target_url=target_url,
        account=user,
        status=status,
        message=msg,
    )
    return {"user": user, "code": code, "status": status, "result": result}


async def _submit_parallel_for_mm88(
    codes: list,
    available_accounts: list,
    target_url: str,
    channel_name: str,
    domain: str,
):
    """MM88 submit SONG SONG."""
    if not codes or not available_accounts:
        return

    unique_codes = list(dict.fromkeys(codes))
    n_acc = len(available_accounts)
    assignments = []

    if len(unique_codes) >= n_acc:
        for i, acc in enumerate(available_accounts):
            assignments.append((acc, unique_codes[i]))
        logger.info(
            f"🎯 [{domain}] {n_acc} acc ↔ {n_acc} code riêng: "
            + ", ".join(f"{a['username']}→{c}" for a, c in assignments)
        )
    else:
        selected_code = select_random_code(unique_codes)
        for acc in available_accounts:
            assignments.append((acc, selected_code))
        logger.info(
            f"🎯 [{domain}] Chỉ có {len(unique_codes)} code → {n_acc} acc dùng chung: {selected_code}"
        )

    tasks = [
        _submit_one_account(acc, code, target_url, domain) for acc, code in assignments
    ]
    await asyncio.gather(*tasks, return_exceptions=True)


# ============================================================
# OCR PROCESSING
# ============================================================


async def process_image_from_telegram(event, channel_config: dict, systems: dict):
    """Process image with OCR."""
    target_url = channel_config.get("url", "")

    try:
        logger.info("📸 [OCR] Image detected - Processing...")
        temp_dir = tempfile.mkdtemp(prefix="ocr_")

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            image_path = await event.download_media(file=temp_dir)

            if not image_path:
                logger.warning("⚠️ [OCR] Download failed")
                return {
                    "success": False,
                    "codes": [],
                    "message": "Download failed",
                    "text": "",
                }

            # Giữ extension gốc — đổi sang .png gây lỗi nếu file là .jpg/.webp
            orig_ext = Path(image_path).suffix or ".jpg"
            unique_name = f"ocr_{timestamp}{orig_ext}"
            unique_path = Path(temp_dir) / unique_name
            Path(image_path).rename(unique_path)
            image_path = str(unique_path)

            logger.info(f"✅ [OCR] Downloaded: {unique_name}")

            extractor = get_image_extractor()
            if extractor is None:
                logger.error("❌ [OCR] Tesseract not installed")
                return {
                    "success": False,
                    "codes": [],
                    "message": "Tesseract not installed",
                    "text": "",
                }

            loop = asyncio.get_running_loop()

            def _run_ocr():
                text = extractor.extract_code_from_image(image_path, lang="eng")
                if not text or len(text.strip()) < 3:
                    logger.debug(f"⚠️ [OCR] English failed, trying Vietnamese...")
                    text = extractor.extract_code_from_image(image_path, lang="vie+eng")
                return text or ""

            extracted_text = await loop.run_in_executor(None, _run_ocr)

            if not extracted_text:
                logger.warning("⚠️ [OCR] No text detected in image")
                return {
                    "success": False,
                    "codes": [],
                    "message": "No text in image",
                    "text": "",
                }

            # ── LLwin: xoá chú thích "code bỏ số X / code bỏ chữ X" ────────
            ocr_group = get_filter_group_name(target_url)
            if ocr_group == "llwin":
                original_len = len(extracted_text)
                extracted_text = clean_llwin_ocr_text(extracted_text)
                if len(extracted_text) != original_len:
                    logger.info(
                        f"🧹 [LLwin-OCR] Đã xoá chú thích 'code bỏ...' "
                        f"({original_len}→{len(extracted_text)} chars)"
                    )

            logger.info(
                f"✅ [OCR] Extracted {len(extracted_text)} chars: {extracted_text[:80]}"
            )

            extracted_codes = []
            for line in extracted_text.split("\n"):
                line = line.strip()
                if len(line) < 4:
                    continue

                clean_code = CodeValidator.clean_code(line)
                if not clean_code or len(clean_code) < 4:
                    continue

                try:
                    validation = CodeValidator.validate_code(
                        clean_code, target_url=target_url, source="image_ocr"
                    )
                except TypeError:
                    validation = CodeValidator.validate_code(clean_code, target_url)

                if validation["valid"]:
                    extracted_codes.append(
                        {"code": clean_code, "raw": line, "confidence": 0.9}
                    )
                    logger.info(f"✅ [OCR] CODE: {clean_code}")
                else:
                    logger.debug(
                        f"⚠️ [OCR] Invalid: {clean_code} - {validation['reason']}"
                    )

            if extracted_codes:
                logger.info(f"✅ [OCR] Found {len(extracted_codes)} valid code(s)")
                return {
                    "success": True,
                    "codes": extracted_codes,
                    "message": f"{len(extracted_codes)} code(s)",
                    "text": extracted_text,
                }

            logger.warning("⚠️ [OCR] Extracted text but no valid codes found")
            return {
                "success": False,
                "codes": [],
                "message": "No valid codes extracted",
                "text": extracted_text,
            }

        finally:
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

    except Exception as e:
        logger.error(f"❌ [OCR] Error: {e}\n{traceback.format_exc()}")
        return {"success": False, "codes": [], "message": f"OCR error: {e}", "text": ""}


async def submit_codes_from_image(
    user: str, codes_data: list, target_url: str, channel_config: dict, systems: dict
):
    """Submit codes extracted from image."""
    if not codes_data:
        return

    domain = normalize_domain(target_url)
    db_ref = systems.get("db") if systems else None
    logger.info(f"📤 [IMG] Submitting {len(codes_data)} code(s) for {user}")

    for idx, code_item in enumerate(codes_data, 1):
        code = code_item.get("code", "").strip()
        if not code:
            continue

        if db_ref is not None:
            try:
                loop = asyncio.get_running_loop()
                marked_ok = await loop.run_in_executor(
                    None, db_ref.mark_code_used, domain, code
                )
            except Exception as e:
                logger.debug(f"⚠️ mark_code_used error: {e}")
                marked_ok = True
            if not marked_ok:
                logger.warning(
                    f"⏭️ [OCR#{idx}] [DEDUP-VĨNH VIỄN] {code} đã từng xử lý → bỏ qua"
                )
                continue

        try:
            result = await submit_code_with_delay(user, code, target_url, systems)
            status = "✅" if (result and result.get("success")) else "❌"
            logger.info(f"  {status} [OCR#{idx}] {code}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"  ❌ [OCR#{idx}] Error: {e}")


# ============================================================
# MESSAGE PROCESSING
# ============================================================


async def process_telegram_message(event):
    """Process Telegram message."""
    if not _systems:
        return

    # ✅ KIỂM TRA NGAY - không để delay
    if event.chat_id not in Config.CHANNEL_CONFIG:
        logger.debug(f"⏭️ Chat {event.chat_id} not in config")
        return

    channel_config = Config.CHANNEL_CONFIG.get(event.chat_id)
    if not channel_config:
        return

    # ✅ KIỂM TRA NGAY - bỏ qua tin cũ
    msg_date = event.message.date
    if msg_date.tzinfo is None:
        msg_date = msg_date.replace(tzinfo=timezone.utc)

    if msg_date < BOT_START_TIME:
        logger.debug(f"⏭️ [OLD MSG] Skip ({msg_date} < {BOT_START_TIME})")
        return

    target_url = channel_config["url"]
    accounts = channel_config["accounts"]
    # Telethon: tin nhắn có media (ảnh+text) lưu text ở .message, không phải .text
    raw_text = (event.message.text or event.message.message or "").strip()
    group_name = get_filter_group_name(target_url)

    # ✅ DEBUG: Log raw message
    logger.warning(
        f"📝 MESSAGE RAW | channel={channel_config.get('name', 'N/A')} | "
        f"text_len={len(raw_text)} | text={raw_text[:200]}"
    )
    # ✅ DEBUG: Log entities
    if event.message.entities:
        logger.debug(f"   Entities: {[type(e).__name__ for e in event.message.entities]}")

    logger.info(f"\n👀 [{channel_config['name']}] NEW MESSAGE")

    # ── QQ88: lọc tin ────────────────────────────────────────────────────────
    # Caption code thực tế: "FREE CODE :gbu3Q1GvT8", "GIFT CODE:...", "nhập code", "tangquaqq88.com"
    QQ88_OCR_TRIGGER = [
        "tangquaqq88.com",
        "link nhập code",
        "link nhap code",
        "tangquaqq88",
        "nhập code",
        "nhap code",
        "free code",
        "freecode",
        "gift code",
        "giftcode",
        "tặng code",
        "tang code",
        "mã code",
        "ma code",
    ]
    QQ88_OCR_SKIP = [
        "khuyến mãi",
        "khuyen mai",
        "giảm giá",
        "sale",
        "promo",
        "quảng cáo",
        "nạp tiền",
    ]

    if group_name == "qq88":
        caption_text = (event.message.message or raw_text or "").strip().lower()
        has_media = bool(event.media)
        has_raw_text = bool(raw_text.strip())

        if has_raw_text:
            logger.info("✅ [QQ88] Text/spoiler → xử lý ngay")
        elif has_media:
            if any(kw in caption_text for kw in QQ88_OCR_SKIP):
                logger.info(
                    f"⏭️ [QQ88] Ảnh quảng cáo → bỏ qua (caption: {caption_text[:80]})"
                )
                return
            if any(kw in caption_text for kw in QQ88_OCR_TRIGGER):
                logger.info(
                    f"✅ [QQ88] Caption có trigger code → OCR (caption: {caption_text[:80]})"
                )
            else:
                logger.info(
                    f"⏭️ [QQ88] Caption không có trigger → bỏ qua (caption: {caption_text[:80]})"
                )
                return
        else:
            logger.info("⏭️ [QQ88] Không có text lẫn ảnh → bỏ qua")
            return

    # ── XỬ LÝ ẢNH ────────────────────────────────────────────────────────────
    if event.media and not raw_text:
        # Caption trong Telethon nằm ở .message (không phải .caption)
        caption = (getattr(event.message, "message", None) or "").strip()
        caption_lower = caption.lower()

        AD_KEYWORDS = [
            "khuyến mãi",
            "khuyen mai",
            "km ",
            "sale",
            "giảm giá",
            "giam gia",
            "promo",
            "quảng cáo",
            "quang cao",
            "qc ",
            "tấu",
            "khmerads",
            "nạp tiền",
            "nap tien",
            "ưu đãi",
            "uu dai",
            "hoàn tiền",
            "cashback",
            "event",
            "sự kiện",
            "su kien",
            "thông báo",
        ]
        if any(kw in caption_lower for kw in AD_KEYWORDS):
            logger.info(f"⏭️ [IMG] Ad image detected → skip")
            return

        default_account = accounts[0]["username"] if accounts else None
        if not default_account:
            return

        # ✅ UY88/MMOO FIX: Kênh hay gửi ảnh trước, caption/spoiler đến sau qua MessageEdited.
        # Nếu caption TRỐNG và raw_text cũng TRỐNG → lưu pending chờ edit.
        # Nếu raw_text đã có (text kèm ảnh) → xử lý text ngay, không cần pending.
        if group_name in ("uy88", "mmoo") and not caption and not raw_text:
            pending_key = (event.chat_id, event.message.id)
            bot_state._pending_image_msgs[pending_key] = (event, time.time())
            logger.info(
                f"⏳ [{group_name.upper()}] Ảnh chưa có caption — lưu pending (msg_id={event.message.id}), "
                f"chờ MessageEdited tối đa {bot_state._PENDING_IMAGE_TTL:.0f}s"
            )
            return

        # Caption đã có (hoặc kênh khác) → xử lý text từ caption trước
        if caption:
            logger.info(
                f"🖼️+📝 Image với caption ({len(caption)} chars) → extract code từ caption"
            )
            # Xử lý caption như text thường (spoiler, marker, regex)
            extracted = extract_codes_from_message(event, caption, target_url)
            if extracted:
                logger.info(f"✅ [IMG-CAPTION] Codes từ caption: {extracted}")
                raw_text = caption  # chuyển sang nhánh text bên dưới
                # fall-through: tiếp tục xử lý như tin nhắn text
            else:
                # Caption có nhưng không có code → thử OCR ảnh
                logger.info("🖼️ Caption không có code → OCR ảnh")

                async def _handle_image_task_with_caption():
                    try:
                        ocr_result = await process_image_from_telegram(
                            event, channel_config=channel_config, systems=_systems
                        )
                        if ocr_result["success"]:
                            await submit_codes_from_image(
                                user=default_account,
                                codes_data=ocr_result["codes"],
                                target_url=target_url,
                                channel_config=channel_config,
                                systems=_systems,
                            )
                        else:
                            logger.warning(f"⚠️ OCR failed: {ocr_result['message']}")
                    except Exception as e:
                        logger.error(f"❌ Image task error: {e}")

                img_task = asyncio.create_task(_handle_image_task_with_caption())
                track_submit_task(
                    img_task, label=f"img|{channel_config.get('name','')}"
                )
                # Xóa pending_key sau khi đã dispatch xử lý
                pending_key = (event.chat_id, event.message.id)
                bot_state._pending_image_msgs.pop(pending_key, None)
                return
        else:
            # Không caption, không phải UY88 → OCR
            logger.info("🖼️ Image không caption → OCR")

            async def _handle_image_task_no_caption():
                try:
                    ocr_result = await process_image_from_telegram(
                        event, channel_config=channel_config, systems=_systems
                    )
                    if ocr_result["success"]:
                        await submit_codes_from_image(
                            user=default_account,
                            codes_data=ocr_result["codes"],
                            target_url=target_url,
                            channel_config=channel_config,
                            systems=_systems,
                        )
                    else:
                        logger.warning(f"⚠️ OCR failed: {ocr_result['message']}")
                except Exception as e:
                    logger.error(f"❌ Image task error: {e}")

            img_task = asyncio.create_task(_handle_image_task_no_caption())
            track_submit_task(img_task, label=f"img|{channel_config.get('name','')}")
            # Xóa pending_key sau khi đã dispatch xử lý
            pending_key = (event.chat_id, event.message.id)
            bot_state._pending_image_msgs.pop(pending_key, None)
            return

    # Measure delay
    msg_timestamp = event.message.date
    telegram_delay = measure_telegram_delay_fast(msg_timestamp)
    if telegram_delay is not None:
        logger.warning(f"⏱️ Delay: {telegram_delay:.2f}s")

    # Extract codes
    final_codes = extract_codes_from_message(event, raw_text, target_url)
    if not final_codes:
        logger.warning(f"❌ NO CODES FOUND | channel={channel_config.get('name', 'N/A')}")
        logger.debug(f"   Raw text: {raw_text[:300]}")
        logger.debug(f"   Entities: {event.message.entities}")
        logger.debug(f"   Media: {event.media}")
        return

    logger.warning(f"✅ CODES EXTRACTED | count={len(final_codes)} | codes={final_codes}")

    for code in final_codes:
        append_code_history(
            event_type="DETECTED",
            code=code,
            target_url=target_url,
            channel=channel_config.get("name", ""),
            source="telegram",
            status="PENDING",
            telegram_delay=telegram_delay,
        )

    # Dedup
    domain = normalize_domain(target_url)
    final_codes_dedup = []
    db_ref = _systems["db"] if _systems else None
    for code in final_codes:
        if db_ref is not None:
            try:
                loop = asyncio.get_running_loop()
                marked_ok = await loop.run_in_executor(
                    None, db_ref.mark_code_used, domain, code
                )
            except Exception as e:
                logger.debug(f"⚠️ mark_code_used error: {e}")
                marked_ok = True
            if not marked_ok:
                logger.warning(f"⏭️ [DEDUP-VĨNH VIỄN] {code} đã từng xử lý → bỏ qua")
                continue
        if is_site_code_duplicate(domain, code):
            logger.warning(f"⏭️ [DEDUP] {code} recently submitted")
        else:
            final_codes_dedup.append(code)

    if not final_codes_dedup:
        logger.info("⏭️ All codes deduped")
        return

    # Submit
    available_accounts = sorted(accounts, key=lambda a: a.get("priority", 999))
    if not available_accounts:
        return

    # MM88 parallel mode
    if domain == "mm88code.com" and len(available_accounts) >= 2:
        # ✅ Kiểm tra giờ hoạt động MM88 (12:00 - 16:00)
        if not _is_mm88_active_hours():
            logger.info(
                f"⏰ [MM88] Ngoài giờ 12:00-16:00 → bỏ qua tin này "
                f"(hiện tại: {datetime.now().strftime('%H:%M')})"
            )
            return

        # ✅ Kiểm tra còn tài khoản nào chưa dùng hôm nay không
        active_mm88 = [
            a for a in available_accounts
            if not _is_account_done_today(f"{domain}|{a['username']}", a["username"])
        ]
        if not active_mm88:
            logger.info(f"✅ [MM88] Tất cả tài khoản đã nhập xong hôm nay → bỏ qua")
            return

        missing = [
            a["username"]
            for a in active_mm88
            if f"{domain}|{a['username']}" not in bot_state.account_pages
        ]
        if len(missing) == len(active_mm88):
            logger.warning(f"⚠️ [{domain}] Không có tab nào sẵn sàng (có thể đã đóng sau khi dùng xong)")
            return

        task = asyncio.create_task(
            _submit_parallel_for_mm88(
                codes=final_codes_dedup,
                available_accounts=active_mm88,
                target_url=target_url,
                channel_name=channel_config.get("name", ""),
                domain=domain,
            )
        )
        track_submit_task(task, label=f"parallel|{domain}|{len(final_codes_dedup)}")
        logger.warning(
            f"⚡ [PARALLEL MM88] {len(final_codes_dedup)} code(s) → {len(active_mm88)} acc → '{channel_config['name']}'"
        )
        return

    # Sequential mode (1 tab duy nhất)
    # ✅ Kiểm tra còn tài khoản nào chưa dùng hôm nay không
    next_available = _get_next_available_account(domain, available_accounts)
    if next_available is None:
        logger.info(f"✅ [{domain}] Tất cả tài khoản đã nhập xong hôm nay → bỏ qua")
        return

    # Kiểm tra kênh đã được đăng ký không (context_locks được điền lúc preload,
    # account_pages chỉ được điền sau khi tab navigate lần đầu → không dùng để check)
    has_any_tab = (domain in bot_state.context_locks) or (domain in bot_state.account_pages)
    if not has_any_tab:
        logger.warning(f"⚠️ [{domain}] Kênh chưa được đăng ký (không có trong context_locks hay account_pages)")
        return

    task = asyncio.create_task(
        _submit_sequential_for_channel(
            codes=final_codes_dedup,
            available_accounts=available_accounts,
            target_url=target_url,
            channel_name=channel_config.get("name", ""),
            domain=domain,
        )
    )
    track_submit_task(task, label=f"seq|{domain}|{len(final_codes_dedup)}")
    logger.warning(
        f"⚡ Task: {len(final_codes_dedup)} code(s) → [{next_available['username']}] → '{channel_config['name']}'"
    )


# ============================================================
# MESSAGE WORKERS
# ============================================================


# ✅ Semaphore giới hạn số lượng process_telegram_message chạy đồng thời
# Tránh tình trạng burst 50 tin → 50 task cùng tranh DB lock
_proc_semaphore: asyncio.Semaphore | None = None

def _get_proc_semaphore() -> asyncio.Semaphore:
    global _proc_semaphore
    if _proc_semaphore is None:
        limit = int(getattr(Config, "MAX_CONCURRENT_PROCESSING", 24))
        _proc_semaphore = asyncio.Semaphore(limit)
    return _proc_semaphore


async def _safe_dispatch(event, worker_id: int):
    """
    Bọc process_telegram_message trong semaphore.
    Chạy như asyncio.Task riêng — không block worker.
    """
    try:
        async with _get_proc_semaphore():
            await process_telegram_message(event)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"❌ [dispatch|w{worker_id}] {type(e).__name__}: {e}")


async def message_worker(worker_id: int):
    """
    Message worker v2 — ZERO-BLOCK DISPATCH.

    Thiết kế cũ (bottleneck):
        get event → await process_telegram_message()  ← block 10-50ms → get next
        → với 4 workers, 15 kênh cùng gửi = 11 tin phải chờ

    Thiết kế mới:
        get event → create_task(_safe_dispatch()) [<0.1ms] → get next NGAY
        → 2 workers xử lý 1000+ tin/giây, không bao giờ tắc nghẽn
    """
    global message_queue
    logger.info(f"👷 Worker #{worker_id} started (zero-block dispatch mode)")

    while bot_state.is_running:
        try:
            event = await asyncio.wait_for(message_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(0.01)
            continue

        # ✅ CORE FIX: create_task ngay, task_done ngay → worker FREE NGAY
        # process_telegram_message chạy song song trong task riêng
        task = asyncio.create_task(
            _safe_dispatch(event, worker_id),
            name=f"proc|{event.chat_id}|{event.message.id}",
        )
        _active_submit_tasks.add(task)
        task.add_done_callback(_active_submit_tasks.discard)
        try:
            message_queue.task_done()
        except Exception:
            pass


def start_message_workers():
    """
    Start message workers — v2 zero-block dispatch mode.

    Với thiết kế mới (worker không await processing), chỉ cần 2 workers
    là đủ xử lý hàng nghìn tin/giây vì mỗi worker dispatch task trong <0.1ms.
    Tăng queue size lên 2000 để buffer burst lớn (toàn bộ 15 kênh cùng gửi).
    """
    global message_queue, message_workers

    queue_maxsize = int(getattr(Config, "MESSAGE_QUEUE_MAXSIZE", 2000))
    # ✅ 2 workers là đủ trong dispatch mode (mỗi worker dispatch <0.1ms/tin)
    # Tăng lên 4 nếu muốn thêm buffer khi burst cực lớn
    worker_count = int(getattr(Config, "MESSAGE_WORKERS", 2))

    if message_queue is None:
        message_queue = asyncio.Queue(maxsize=queue_maxsize)

    if message_workers:
        return

    for wid in range(1, worker_count + 1):
        message_workers.append(asyncio.create_task(message_worker(wid), name=f"worker-{wid}"))

    logger.info(
        f"🚀 Message workers started: count={worker_count} | queue_max={queue_maxsize} "
        f"| proc_concurrent={getattr(Config, 'MAX_CONCURRENT_PROCESSING', 24)}"
    )


# ============================================================
# TELEGRAM HANDLER
# ============================================================

# ============================================================
# UY88 EDITED MESSAGE HANDLER
# ============================================================


async def _cleanup_pending_images():
    """d) Xóa pending image hết TTL — thử OCR trước khi xóa."""
    now = time.time()
    ttl = bot_state._PENDING_IMAGE_TTL
    expired = [
        k for k, (_, ts) in bot_state._pending_image_msgs.items() if now - ts > ttl
    ]
    for k in expired:
        event, ts = bot_state._pending_image_msgs.pop(k, (None, None))
        if event is None:
            continue
        logger.info(f"⏰ [PENDING] Hết TTL {ttl:.0f}s — thử OCR ảnh (msg_id={k[1]})")
        try:
            chat_id = k[0]
            channel_config = Config.CHANNEL_CONFIG.get(chat_id)
            if channel_config and _systems:
                target_url = channel_config["url"]
                accounts = channel_config.get("accounts", [])
                default_account = accounts[0]["username"] if accounts else ""

                async def _ocr_expired(
                    ev=event, url=target_url, cfg=channel_config, acc=default_account
                ):
                    try:
                        ocr_result = await process_image_from_telegram(
                            ev, channel_config=cfg, systems=_systems
                        )
                        if ocr_result.get("success"):
                            logger.info(f"✅ [PENDING-OCR] OCR tìm được code sau TTL")
                            await submit_codes_from_image(
                                user=acc,
                                codes_data=ocr_result["codes"],
                                target_url=url,
                                channel_config=cfg,
                                systems=_systems,
                            )
                        else:
                            logger.warning(
                                f"⚠️ [PENDING-OCR] OCR không tìm được code: {ocr_result.get('message','')}"
                            )
                    except Exception as ocr_err:
                        logger.error(f"❌ [PENDING-OCR] Lỗi: {ocr_err}")

                ocr_task = asyncio.create_task(_ocr_expired())
                track_submit_task(ocr_task, label=f"pending-ocr|{k[1]}")
        except Exception as e:
            logger.debug(f"⚠️ [PENDING] OCR fallback error: {e}")
    return len(expired)


async def process_edited_message(event):
    """
    Xử lý MessageEdited — dành cho trường hợp caption xuất hiện SAU khi ảnh đã gửi.
    Luồng: ảnh gửi trước (NewMessage, không caption) → bot lưu pending
           caption/spoiler đến sau (MessageEdited) → bot bắt và xử lý code.
    """
    if not _systems:
        return

    chat_id = event.chat_id
    if chat_id not in Config.CHANNEL_CONFIG:
        return

    # Chỉ quan tâm tin có trong pending (đã thấy ảnh trước)
    msg_id = event.message.id
    pending_key = (chat_id, msg_id)

    channel_config = Config.CHANNEL_CONFIG[chat_id]
    target_url = channel_config["url"]
    group_name = get_filter_group_name(target_url)
    accounts = channel_config["accounts"]

    # Lấy text mới nhất từ edited message
    new_text = (event.message.text or event.message.message or "").strip()

    if pending_key in bot_state._pending_image_msgs:
        # ── CASE 1: Đây là edit cho ảnh đang pending ──────────────────────
        orig_event, pending_ts = bot_state._pending_image_msgs.pop(pending_key)
        wait_secs = time.time() - pending_ts
        logger.info(
            f"✏️ [{group_name.upper()}-EDIT] Caption đến sau {wait_secs:.1f}s cho msg_id={msg_id} "
            f"| chat={channel_config['name']} | text={new_text[:80]}"
        )

        if not new_text:
            logger.info(f"⏭️ [{group_name.upper()}-EDIT] Edit nhưng vẫn không có text → bỏ qua")
            return

        # Extract code từ caption mới (ưu tiên spoiler)
        extracted = extract_codes_from_message(event, new_text, target_url)
        if not extracted:
            logger.info(
                f"⏭️ [{group_name.upper()}-EDIT] Không tìm thấy code trong caption: {new_text[:60]}"
            )
            return

        logger.info(f"🎯 [{group_name.upper()}-EDIT] Codes từ caption muộn: {extracted}")

        # Dedup + submit (giống luồng text thường)
        domain = normalize_domain(target_url)
        db_ref = _systems["db"] if _systems else None
        final_codes = []
        for code in extracted:
            if db_ref is not None:
                try:
                    loop = asyncio.get_running_loop()
                    ok = await loop.run_in_executor(
                        None, db_ref.mark_code_used, domain, code
                    )
                except Exception:
                    ok = True
                if not ok:
                    logger.warning(f"⏭️ [{group_name.upper()}-EDIT DEDUP] {code} đã xử lý rồi")
                    continue
            if is_site_code_duplicate(domain, code):
                logger.warning(f"⏭️ [{group_name.upper()}-EDIT DEDUP-TTL] {code} vừa submit")
            else:
                final_codes.append(code)

        if not final_codes:
            return

        available_accounts = sorted(accounts, key=lambda a: a.get("priority", 999))
        task = asyncio.create_task(
            _submit_sequential_for_channel(
                codes=final_codes,
                available_accounts=available_accounts,
                target_url=target_url,
                channel_name=channel_config.get("name", ""),
                domain=domain,
            )
        )
        track_submit_task(task, label=f"{group_name}_edit|{domain}|{msg_id}")
        logger.info(f"⚡ [{group_name.upper()}-EDIT] Submit task created: {final_codes}")

    else:
        # ── CASE 2: Edit thông thường (không phải ảnh pending) ────────────
        # Chỉ xử lý nếu kênh là UY88 và có text mới
        if group_name not in ("uy88", "mmoo") or not new_text:
            return

        # Kiểm tra tin có đủ mới không (trong vòng 5 phút kể từ gửi)
        msg_date = event.message.date
        if msg_date.tzinfo is None:
            msg_date = msg_date.replace(tzinfo=timezone.utc)
        age_secs = (datetime.now(timezone.utc) - msg_date).total_seconds()
        if age_secs > 300:
            logger.debug(f"⏭️ [{group_name.upper()}-EDIT] Tin quá cũ ({age_secs:.0f}s) → bỏ qua")
            return
        if msg_date < BOT_START_TIME:
            return

        logger.info(f"✏️ [{group_name.upper()}-EDIT] Edit trên tin text: {new_text[:60]}")
        extracted = extract_codes_from_message(event, new_text, target_url)
        if not extracted:
            return

        domain = normalize_domain(target_url)
        db_ref = _systems["db"] if _systems else None
        final_codes = []
        for code in extracted:
            if db_ref is not None:
                try:
                    loop = asyncio.get_running_loop()
                    ok = await loop.run_in_executor(
                        None, db_ref.mark_code_used, domain, code
                    )
                except Exception:
                    ok = True
                if not ok:
                    continue
            if not is_site_code_duplicate(domain, code):
                final_codes.append(code)

        if not final_codes:
            return

        available_accounts = sorted(accounts, key=lambda a: a.get("priority", 999))
        task = asyncio.create_task(
            _submit_sequential_for_channel(
                codes=final_codes,
                available_accounts=available_accounts,
                target_url=target_url,
                channel_name=channel_config.get("name", ""),
                domain=domain,
            )
        )
        track_submit_task(task, label=f"uy88_edit_text|{domain}|{msg_id}")
        logger.info(f"⚡ [{group_name.upper()}-EDIT-TEXT] Submit task: {final_codes}")


async def setup_telegram_handler():
    """Setup Telegram message handler — zero-latency dispatch"""
    if bot_state.handler_registered:
        logger.warning("⚠️ Handler đã đăng ký trước đây — bỏ qua")
        return

    channel_ids = list(Config.CHANNEL_CONFIG.keys())
    if not channel_ids:
        logger.error("❌ No channels in CONFIG")
        return

    logger.warning(f"🔧 Đang đăng ký handler cho {len(channel_ids)} kênh...")

    start_message_workers()

    @client.on(events.NewMessage())
    async def handler(event):
        try:
            # ── RAW EVENT LOG: dùng để debug xem handler có được gọi không ──
            logger.warning(
                f"📨 RAW EVENT | chat={event.chat_id} | id={event.message.id if event.message else 'N/A'} | "
                f"text={str(event.message.text or event.message.message or '')[:100] if event.message else 'N/A'}"
            )

            if not event.message:
                logger.debug("⏭️ No message in event")
                return
            msg_date = event.message.date
            if msg_date is None:
                logger.debug("⏭️ No date in message")
                return
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)

            # ── Filter tin cũ (so sánh UTC với UTC) ──────────────────────────
            logger.debug(
                f"⏰ FILTER CHECK | msg_date={msg_date.isoformat()} | "
                f"BOT_START_TIME={BOT_START_TIME.isoformat()} | "
                f"pass={msg_date >= BOT_START_TIME}"
            )
            if msg_date < BOT_START_TIME:
                logger.debug(
                    f"⏭️ [OLD] {msg_date.strftime('%H:%M:%S')} UTC < {BOT_START_TIME.strftime('%H:%M:%S')} UTC"
                )
                return

            if event.chat_id not in Config.CHANNEL_CONFIG:
                logger.debug(f"⏭️ Chat {event.chat_id} not configured")
                return

            # ── Dispatch vào queue hoặc trực tiếp ────────────────────────────
            if message_queue is not None:
                try:
                    message_queue.put_nowait(event)
                    logger.debug(f"✅ Enqueued | queue_size={message_queue.qsize()}")
                except asyncio.QueueFull:
                    logger.warning(f"⚠️ Queue đầy! Bypass → direct dispatch chat={event.chat_id}")
                    task = asyncio.create_task(
                        _safe_dispatch(event, worker_id=0),
                        name=f"bypass|{event.chat_id}|{event.message.id}",
                    )
                    _active_submit_tasks.add(task)
                    task.add_done_callback(_active_submit_tasks.discard)
            else:
                task = asyncio.create_task(
                    _safe_dispatch(event, worker_id=0),
                    name=f"fb|{event.chat_id}|{event.message.id}",
                )
                _active_submit_tasks.add(task)
                task.add_done_callback(_active_submit_tasks.discard)
        except Exception as e:
            logger.warning(f"⚠️ handler error: {e}\n{traceback.format_exc()}")

    # ✅ UY88: bắt caption xuất hiện muộn (MessageEdited)
    @client.on(events.MessageEdited())
    async def edit_handler(event):
        if event.chat_id not in Config.CHANNEL_CONFIG:
            return
        msg_date = event.message.date
        if msg_date.tzinfo is None:
            msg_date = msg_date.replace(tzinfo=timezone.utc)
        if msg_date < BOT_START_TIME:
            return
        asyncio.create_task(
            process_edited_message(event),
            name=f"edit|{event.chat_id}|{event.message.id}",
        )

    bot_state.handler_registered = True
    logger.info(
        f"✅ Handler ready | channels={len(channel_ids)} | +MessageEdited | "
        f"dispatch_mode=zero-block | proc_sem={getattr(Config, 'MAX_CONCURRENT_PROCESSING', 24)}"
    )


# ============================================================
# WATCHDOGS
# ============================================================


async def auto_fill_usernames_watchdog():
    """Auto-fill usernames when empty."""
    last_filled_time: dict = {}

    while bot_state.is_running:
        try:
            await asyncio.sleep(10)

            if not bot_state.account_pages:
                continue

            for domain_key, page in list(bot_state.account_pages.items()):
                try:
                    if page.is_closed():
                        last_filled_time.pop(domain_key, None)
                        continue

                    username_input, _ = await find_input_fields(page, cache_key=None)
                    if not username_input:
                        continue

                    current_value = await get_input_value(username_input)
                    if current_value.strip():
                        last_filled_time.pop(domain_key, None)
                        continue

                    now = time.time()
                    last_filled = last_filled_time.get(domain_key)
                    if last_filled and (now - last_filled) < 300:
                        continue

                    default_user = get_default_account_for_domain(domain_key)
                    if not default_user:
                        continue

                    await page.evaluate(
                        "([el, val]) => { el.value = val; "
                        "el.dispatchEvent(new Event('input', {bubbles:true})); "
                        "el.dispatchEvent(new Event('change', {bubbles:true})); }",
                        [username_input, default_user],
                    )
                    logger.info(f"🔄 [{domain_key}] Auto-filled username")
                    last_filled_time[domain_key] = now

                except Exception as e:
                    logger.debug(f"⚠️ Username watchdog error: {e}")

        except asyncio.CancelledError:
            break
        except Exception:
            pass


async def cdp_health_watchdog():
    """
    Playwright Browser Health Watchdog (v7.5).
    Thay thế CDP watchdog cũ (Edge+CDP đã loại bỏ).
    Định kỳ kiểm tra từng page còn sống không — nếu đóng thì reopen.
    """
    CHECK_INTERVAL = float(getattr(Config, "CDP_PING_INTERVAL", 60.0))

    while bot_state.is_running:
        try:
            await asyncio.sleep(CHECK_INTERVAL)

            stale_keys = []
            for key, page in list(bot_state.account_pages.items()):
                try:
                    closed = page.is_closed()
                except Exception:
                    closed = True
                if closed:
                    stale_keys.append(key)

            if not stale_keys:
                logger.debug("✅ [Browser-Watchdog] Tất cả tab OK")
                continue

            logger.warning(
                f"⚠️ [Browser-Watchdog] Phát hiện {len(stale_keys)} tab đóng: {stale_keys}"
            )
            for key in stale_keys:
                # Tìm target_url của key
                domain = key.split("|")[0] if "|" in key else key
                target_url = None
                for cfg in Config.CHANNEL_CONFIG.values():
                    from urllib.parse import urlparse as _up
                    if _up(cfg["url"]).netloc.replace("www.", "") == domain:
                        target_url = cfg["url"]
                        break

                if not target_url:
                    # Không tìm được URL → chỉ dọn state
                    bot_state.account_pages.pop(key, None)
                    bot_state.context_locks.pop(key, None)
                    bot_state._input_cache.pop(key, None)
                    bot_state._tab_fail_count.pop(key, None)
                    logger.warning(f"🧹 [Browser-Watchdog] Xóa stale key (no URL): {key}")
                    continue

                try:
                    # Lấy context từ playwright instance để mở tab mới
                    pw = getattr(bot_state, "playwright_instance", None)
                    if pw is None:
                        logger.warning(f"⚠️ [Browser-Watchdog] Không có playwright instance")
                        continue

                    # Tìm context hiện có (nếu còn)
                    old_page = bot_state.account_pages.get(key)
                    ctx = None
                    try:
                        if old_page and not old_page.is_closed():
                            ctx = old_page.context
                        elif old_page:
                            ctx = old_page.context  # context có thể vẫn alive dù page đóng
                    except Exception:
                        ctx = None

                    if ctx is None:
                        logger.warning(f"⚠️ [Browser-Watchdog] Không lấy được context cho {key}")
                        bot_state.account_pages.pop(key, None)
                        bot_state.context_locks.pop(key, None)
                        bot_state._input_cache.pop(key, None)
                        continue

                    new_page = await ctx.new_page()
                    await _setup_page_performance(new_page, domain)
                    await new_page.goto(target_url, wait_until="domcontentloaded", timeout=12000)
                    bot_state.account_pages[key] = new_page
                    bot_state._input_cache.pop(key, None)
                    bot_state._tab_fail_count[key] = 0
                    logger.info(f"✅ [Browser-Watchdog] Đã mở lại tab: {key} → {target_url}")

                except Exception as e:
                    logger.error(f"❌ [Browser-Watchdog] Không mở lại được tab {key}: {e}")
                    bot_state.account_pages.pop(key, None)
                    bot_state.context_locks.pop(key, None)
                    bot_state._input_cache.pop(key, None)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"⚠️ cdp_health_watchdog error: {e}")


async def cloudflare_watchdog():
    """Detect Cloudflare challenges and bring tab to front for manual verification."""
    CF_DETECT_SELECTORS = [
        "iframe[src*='challenges.cloudflare.com']",
        "iframe[src*='turnstile']",
        ".cf-turnstile",
        "[data-sitekey]",
    ]

    while bot_state.is_running:
        try:
            # Poll more frequently so user thấy prompt quickly
            await asyncio.sleep(random.uniform(30.0, 60.0))

            for key, page in list(bot_state.account_pages.items()):
                try:
                    current_url = page.url
                except Exception:
                    continue

                cf_found = False
                try:
                    if "challenges.cloudflare.com" in (current_url or ""):
                        cf_found = True
                    if "/cdn-cgi/challenge-platform" in (current_url or ""):
                        cf_found = True
                except Exception:
                    pass

                if not cf_found:
                    for sel in CF_DETECT_SELECTORS:
                        try:
                            el = await page.query_selector(sel)
                            if el and await el.is_visible():
                                cf_found = True
                                break
                        except Exception:
                            continue

                if cf_found:
                    logger.warning(f"⚠️ Cloudflare [{key}] — please verify manually. Bringing tab to front.")
                    bot_state.cf_verified[key] = False
                    try:
                        await page.bring_to_front()
                    except Exception:
                        pass

        except asyncio.CancelledError:
            break
        except Exception:
            pass


async def close_camoufox_after_submit():
    """
    Đóng hẳn Camoufox sau khi submit xong.
    Lần sau có code mới → lazy init mở lại.
    """
    global _camoufox_instance, _shared_context, _camoufox_hwnd, _tab_pool
    try:
        # Đóng context
        if _shared_context is not None:
            try:
                await _shared_context.close()
            except Exception:
                pass
            _shared_context = None

        # Đóng browser
        if _camoufox_instance is not None:
            try:
                await _camoufox_instance.__aexit__(None, None, None)
            except Exception:
                pass
            _camoufox_instance = None

        # Reset tab pool để lazy init lại lần sau
        _camoufox_hwnd = 0
        _playwright_contexts.clear()
        if _tab_pool is not None:
            _tab_pool._pages.clear()
            _tab_pool._locks.clear()

        logger.info("🔒 Camoufox đã đóng — chờ code tiếp theo")
    except Exception as e:
        logger.debug(f"close_camoufox error: {e}")


async def cleanup_browsers():
    """Close all browser connections."""
    global _camoufox_instance
    # Đóng các context Playwright/Camoufox đang mở
    for key, ctx in list(_playwright_contexts.items()):
        try:
            await ctx.close()
        except Exception:
            pass
    _playwright_contexts.clear()
    # Đóng Camoufox browser instance
    if _camoufox_instance is not None:
        try:
            await _camoufox_instance.__aexit__(None, None, None)
        except Exception:
            pass
        _camoufox_instance = None
    # Legacy CDP browsers
    for port, browser in bot_state.connected_browsers.items():
        try:
            await browser.close()
        except Exception:
            pass


# ============================================================
# MAIN
# ============================================================


async def main():
    """Main entry point."""
    global _systems, BOT_START_TIME

    try:
        logger.info("🚀 BOT v7.5 (PRODUCTION READY)")

        # ── BƯỚC 1: Set BOT_START_TIME TRƯỚC KHI client.start() ──────────────
        # Dùng UTC để so sánh với msg_date của Telegram (luôn là UTC)
        BOT_START_TIME = datetime.now(timezone.utc)
        vn_time = datetime.now()  # giờ local máy (UTC+7)
        logger.info(
            f"⏰ BOT_START_TIME: {vn_time.strftime('%H:%M:%S %d/%m/%Y')} (giờ VN) "
            f"/ {BOT_START_TIME.strftime('%H:%M:%S')} UTC"
        )
        logger.info(f"⏰ Chỉ xử lý tin nhắn MỚI từ thời điểm này trở đi\n")

        _systems = await init_systems()

        await asyncio.sleep(0.5)

        # ── BƯỚC 2: Kết nối Telegram ─────────────────────────────────────────
        logger.warning("🔥 Bắt đầu client.start()...")
        await client.start()
        logger.warning("🔥 client.start() xong")

        # Verify session
        if not await verify_telegram_session():
            return

        # Verify channels
        valid_channels = await verify_channels_and_get_ids()
        if not valid_channels:
            logger.error("❌ No valid channels")
            return

        # ── BƯỚC 3: Preload tabs/keys TRƯỚC khi đăng ký handler ───────────────
        # preload_browsers_and_accounts() chỉ đăng ký keys vào
        # bot_state.context_locks (lazy launch, không mở tab thật ngay).
        # Nhưng _submit_sequential_for_channel() kiểm tra context_locks để
        # quyết định có submit hay không — nếu handler/catch_up chạy TRƯỚC
        # bước này, tin đến sớm sẽ bị "Kênh chưa được đăng ký" và bị drop.
        # => Phải preload xong rồi mới đăng ký handler.
        logger.warning("⭐ Preload browsers & accounts TRƯỚC handler...")
        await preload_browsers_and_accounts()
        logger.info("✅ Preload xong — tab/keys sẵn sàng\n")

        # ── BƯỚC 4: Đăng ký handler (SAU khi context_locks đã sẵn sàng) ──────
        await setup_telegram_handler()

        # ── BƯỚC 5: Catch up các tin nhắn bị bỏ lỡ (SAU khi handler + tabs sẵn sàng) ──
        logger.warning("🔄 Đang catch up các tin nhắn bị bỏ lỡ...")
        await client.catch_up()
        logger.warning("✅ Catch up xong")

        # ── BƯỚC 6: KHÔNG reset lại BOT_START_TIME sau preload nữa ───────────
        # (Trước đây có reset ở đây để né tin đến lúc preload, nhưng việc này
        # cũng vô tình làm rớt các tin catch_up/handler đã nhận được trong lúc
        # preload đang chạy. Giữ nguyên BOT_START_TIME đặt từ đầu hàm main().)
        vn_time_ready = datetime.now()
        logger.info(
            f"✅ BOT READY! Listening from: {vn_time_ready.strftime('%H:%M:%S')} (VN) "
            f"/ {BOT_START_TIME.strftime('%H:%M:%S')} UTC\n"
        )

        # ── BƯỚC 6: Khởi động background tasks ───────────────────────────────
        async def heartbeat_loop():
            while bot_state.is_running:
                try:
                    await asyncio.sleep(300.0)
                    pages = len(bot_state.account_pages)
                    tasks = len(_active_submit_tasks)
                    q_size = message_queue.qsize() if message_queue else 0
                    tg_ok = client.is_connected()
                    vn_now = datetime.now().strftime("%H:%M:%S")
                    logger.info(
                        f"💓 Heartbeat {vn_now} | tabs={pages} | tasks={tasks} | queue={q_size} | tg={tg_ok}"
                    )
                    if tg_ok:
                        try:
                            me = await asyncio.wait_for(client.get_me(), timeout=10.0)
                            if me is None:
                                raise Exception("get_me() returned None")
                            logger.debug(f"✅ Telegram session OK: {me.username or me.id}")
                        except Exception as sess_err:
                            logger.warning(f"⚠️ Telegram session lỗi ({sess_err}) → reconnect...")
                            try:
                                await client.disconnect()
                                await asyncio.sleep(2)
                                await client.start()
                                logger.info("✅ Telegram session reconnect thành công")
                            except Exception as rc_err:
                                logger.error(f"❌ Telegram reconnect thất bại: {rc_err}")
                except asyncio.CancelledError:
                    break
                except Exception:
                    pass

        _bg_tasks = set()
        _bg_tasks.add(asyncio.create_task(heartbeat_loop(), name="heartbeat"))
        _bg_tasks.add(asyncio.create_task(auto_fill_usernames_watchdog(), name="autofill_watchdog"))
        _bg_tasks.add(asyncio.create_task(cloudflare_watchdog(), name="cloudflare_watchdog"))
        _bg_tasks.add(asyncio.create_task(_cleanup_scheduler(), name="cleanup_scheduler"))
        _bg_tasks.add(asyncio.create_task(cdp_health_watchdog(), name="cdp_watchdog"))

        async def daily_reset_watchdog():
            """Reset daily tracking khi qua ngày mới + mở tab MM88 đúng giờ."""
            was_mm88_active = _is_mm88_active_hours()
            while bot_state.is_running:
                try:
                    await asyncio.sleep(60)
                    _refresh_daily_state()

                    now_mm88_active = _is_mm88_active_hours()
                    if not was_mm88_active and now_mm88_active:
                        logger.info("⏰ [MM88] Đã vào giờ hoạt động (12:00-16:00) — tự động mở tab MM88...")
                        try:
                            account_targets = build_unique_account_targets()
                            mm88_targets = [t for t in account_targets if t["domain"] == "mm88code.com"]
                            if mm88_targets:
                                assigned_pages = set(bot_state.account_pages.values())
                                assign_lock = asyncio.Lock()
                                for item in mm88_targets:
                                    await _setup_one_domain_tab(item, assigned_pages, assign_lock)
                                logger.info(f"✅ [MM88] Đã mở {len(mm88_targets)} tab MM88")
                            else:
                                logger.info("ℹ️ [MM88] Không có tab MM88 nào cần mở")
                        except Exception as e:
                            logger.error(f"❌ [MM88] Lỗi khi mở tab MM88: {e}")

                    elif was_mm88_active and not now_mm88_active:
                        logger.info("⏰ [MM88] Đã qua 16:00 — đóng các tab MM88...")
                        mm88_keys = [k for k in list(bot_state.account_pages.keys()) if k.startswith("mm88code.com")]
                        for k in mm88_keys:
                            page = bot_state.account_pages.pop(k, None)
                            bot_state.context_locks.pop(k, None)
                            bot_state._input_cache.pop(k, None)
                            bot_state._page_urls.pop(k, None)
                            bot_state.cf_verified.pop(k, None)
                            if page and not page.is_closed():
                                try:
                                    await page.close()
                                except Exception:
                                    pass
                        if mm88_keys:
                            logger.info(f"✅ [MM88] Đã đóng {len(mm88_keys)} tab MM88")

                    was_mm88_active = now_mm88_active

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug(f"⚠️ daily_reset_watchdog error: {e}")

        _bg_tasks.add(asyncio.create_task(daily_reset_watchdog(), name="daily_reset_watchdog"))

        # ── BƯỚC 7: Main loop ─────────────────────────────────────────────────
        _reconnect_delay = 5.0
        _reconnect_backoff = 1.0

        logger.warning("🔥 Bắt đầu run_until_disconnected()...")
        while bot_state.is_running:
            try:
                if not client.is_connected():
                    logger.warning("🔄 Reconnecting Telegram...")
                    await client.connect()

                await client.run_until_disconnected()

                if not bot_state.is_running:
                    break
                logger.warning("⚠️ Telegram disconnect sạch (logout/ban?) — thử reconnect sau 10s...")
                await asyncio.sleep(10)
                _reconnect_backoff = 1.0

            except (ConnectionError, OSError) as e:
                wait = min(_reconnect_delay * _reconnect_backoff, 60.0)
                logger.warning(f"⚠️ ConnectionError: {e} — Reconnecting in {wait:.0f}s...")
                await asyncio.sleep(wait)
                _reconnect_backoff = min(_reconnect_backoff * 2, 12)

            except Exception as e:
                logger.error(f"❌ Main loop error: {e}\n{traceback.format_exc()}")
                await asyncio.sleep(_reconnect_delay)

    except Exception as e:
        logger.critical(f"❌ Critical error: {e}\n{traceback.format_exc()}")

    finally:
        logger.info("\n🛑 Shutting down...")
        bot_state.is_running = False

        if _history_queue is not None:
            try:
                await asyncio.wait_for(_history_queue.join(), timeout=5.0)
            except Exception:
                pass
            if _history_writer_task:
                _history_writer_task.cancel()

        if _active_submit_tasks:
            logger.info(f"⏳ Waiting for {len(_active_submit_tasks)} tasks...")
            try:
                await asyncio.wait_for(
                    asyncio.gather(*list(_active_submit_tasks), return_exceptions=True),
                    timeout=8.0,
                )
            except Exception:
                for t in list(_active_submit_tasks):
                    t.cancel()

        for worker in message_workers:
            worker.cancel()

        await cleanup_browsers()
        build_daily_summary()

        # ✅ v7.5+: Camoufox đã được đóng trong cleanup_browsers() — không cần stop playwright

        logger.info("✅ Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped")