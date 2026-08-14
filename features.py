"""
✨ THÊM CÁC FEATURES MỚI
Config validation, Statistics, Memory monitoring, Version check
"""

import asyncio
import signal
from logger_setup import logger

# ==========================================
# 📌 VERSION CHECK
# ==========================================

BOT_VERSION = "7.5"
BOT_BUILD_DATE = "2026-06-27"

def print_version_info():
    """In thong tin version - 1 dong gon"""
    try:
        import telethon
        try:
            from importlib.metadata import version as pkg_version
            # ✅ FIX: bot da migrate tu Camoufox sang patchright tu lau,
            # nhung dong log nay van doc version cua camoufox (khong con
            # cai) -> luon in ra "unknown", gay hieu lam. Doi sang patchright.
            patchright_version = pkg_version("patchright")
        except Exception:
            patchright_version = "unknown"

        logger.info(
            f"📦 Bot v{BOT_VERSION} ({BOT_BUILD_DATE}) | "
            f"Telethon {telethon.__version__} | Patchright {patchright_version}"
        )
    except Exception as e:
        logger.error(f"❌ Loi lay version: {e}")


# ==========================================
# 🛡️ GRACEFUL SHUTDOWN HANDLER
# ==========================================

class GracefulShutdownHandler:
    """
    Xu ly tat bot an toan:
    - Ctrl+C  → SIGINT
    - Bam X CMD → CTRL_CLOSE_EVENT (Windows console handler)
    - Shutdown/Logoff → CTRL_SHUTDOWN_EVENT / CTRL_LOGOFF_EVENT
    Cho toi da 8 giay de cleanup roi moi thoat.
    """

    def __init__(self):
        self.shutdown_initiated = False
        self.shutdown_complete = False
        self._event = None   # threading.Event, set khi cleanup xong
        self._loop  = None   # asyncio event loop de cancel tasks

    def setup(self, bot_state):
        """Dang ky ca signal handler (Ctrl+C) va Windows console handler (bam X)."""
        import threading
        self._event = threading.Event()

        # Luu loop de dung call_soon_threadsafe tu thread khac
        try:
            import asyncio as _asyncio
            self._loop = _asyncio.get_event_loop()
        except Exception:
            self._loop = None

        # ── SIGINT / SIGTERM (Ctrl+C, kill) ──────────────────────────────────
        def signal_handler(signum, frame):
            self._do_shutdown(bot_state, reason="SIGINT/SIGTERM")

        try:
            signal.signal(signal.SIGINT,  signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
        except Exception:
            pass

        # ── Windows console handler (bam X, dong CMD, logoff, shutdown) ──────
        try:
            import ctypes, ctypes.wintypes

            CTRL_C_EVENT        = 0
            CTRL_BREAK_EVENT    = 1
            CTRL_CLOSE_EVENT    = 2
            CTRL_LOGOFF_EVENT   = 5
            CTRL_SHUTDOWN_EVENT = 6

            HANDLER_FUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

            _CTRL_EVENT_NAMES = {
                CTRL_C_EVENT: "CTRL_C_EVENT (Ctrl+C)",
                CTRL_BREAK_EVENT: "CTRL_BREAK_EVENT (Ctrl+Break)",
                CTRL_CLOSE_EVENT: "CTRL_CLOSE_EVENT (đóng cửa sổ CMD / bấm X)",
                CTRL_LOGOFF_EVENT: "CTRL_LOGOFF_EVENT (logoff / mất session RDP)",
                CTRL_SHUTDOWN_EVENT: "CTRL_SHUTDOWN_EVENT (Windows shutdown/restart)",
            }

            def _win_handler(ctrl_type):
                if ctrl_type in (CTRL_C_EVENT, CTRL_BREAK_EVENT,
                                 CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT):
                    # ✅ Log rõ LOẠI sự kiện cụ thể để dễ truy nguyên nhân sau này
                    # (trước đây gộp chung "Windows console event", không biết
                    # là do đóng cửa sổ, mất RDP, hay Windows tự shutdown).
                    event_name = _CTRL_EVENT_NAMES.get(ctrl_type, f"unknown_ctrl_type={ctrl_type}")
                    self._do_shutdown(bot_state, reason=event_name)
                    # Cho toi da 8 giay de cleanup
                    self._event.wait(timeout=8)
                    return True   # True = khong de Windows kill ngay
                return False

            self._win_handler_ref = HANDLER_FUNC(_win_handler)   # giu ref tranh GC
            ctypes.windll.kernel32.SetConsoleCtrlHandler(self._win_handler_ref, True)
            logger.info("✅ Graceful shutdown handler setup (Ctrl+C + bam X CMD)")
        except Exception:
            # Khong phai Windows thi bo qua, chi dung signal handler
            logger.info("✅ Graceful shutdown handler setup (signal only)")

    def _do_shutdown(self, bot_state, reason=""):
        """Thuc thi shutdown — chi chay 1 lan duy nhat."""
        if self.shutdown_initiated:
            logger.warning("⚠️ Shutdown lan 2 → Force exit!")
            import os; os._exit(1)
            return

        self.shutdown_initiated = True
        logger.info("=" * 60)
        logger.info(f"🛑 TAT BOT AN TOAN ({reason})")
        logger.info("⏳ Dang don dep... cho toi da 8 giay...")
        logger.info("=" * 60)

        bot_state.is_running = False

        # Cancel event loop de thoat run_until_complete / asyncio.run
        if self._loop and self._loop.is_running():
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass

    def notify_cleanup_done(self):
        """Goi sau khi cleanup xong de giai phong Windows handler."""
        self.shutdown_complete = True
        if self._event:
            self._event.set()

    async def wait_for_shutdown(self, delay: float = 5.0):
        """Cho shutdown xong (dung trong finally block)."""
        await asyncio.sleep(delay)
        self.notify_cleanup_done()

# Global shutdown handler
shutdown_handler = GracefulShutdownHandler()

def get_shutdown_handler() -> GracefulShutdownHandler:
    """Lay shutdown handler"""
    return shutdown_handler