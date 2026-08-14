"""🔒 BROWSER PROFILE MANAGER - Profile riêng biệt cho bot
Không ảnh hưởng tới trình duyệt cá nhân của người dùng
"""

from pathlib import Path
from logger_setup import logger


class BrowserProfileManager:
    """Quản lý profile riêng cho bot - hoàn toàn tách biệt"""

    def __init__(self, profile_base_dir: str = "browser_profiles/bot_profile"):
        self.profile_base_dir = Path(profile_base_dir).resolve()
        self.profile_path = self.profile_base_dir / "Default"
        self._ensure_safe_profile()

    def _ensure_safe_profile(self):
        """Tạo profile bot hoàn toàn riêng biệt"""
        try:
            self.profile_base_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"✅ Profile bot: {self.profile_base_dir}")
        except Exception as e:
            logger.error(f"❌ Lỗi tạo profile: {e}")
            raise

    def cleanup_orphan_processes(self):
        """Dọn các Edge process cũ chỉ dùng profile bot này"""
        try:
            import psutil
            profile_path_str = str(self.profile_base_dir).lower()
            orphans = []

            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    name = (proc.info.get("name") or "").lower()
                    if name not in ("msedge.exe", "msedge"):
                        continue
                    cmdline = " ".join(proc.info.get("cmdline") or [])
                    # Chỉ xóa Edge dùng PROFILE BOT, không xóa Edge cá nhân
                    if profile_path_str in cmdline.lower():
                        orphans.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if orphans:
                logger.info(f"🧹 Tìm {len(orphans)} Edge process cũ (bot profile)")
                for proc in orphans:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                gone, alive = psutil.wait_procs(orphans, timeout=3)
                for proc in alive:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                logger.info(f"✅ Đã dọn {len(orphans)} process")
        except ImportError:
            logger.debug("⚠️ psutil chưa cài - bỏ qua cleanup")
        except Exception as e:
            logger.debug(f"⚠️ Cleanup orphan error: {e}")

    def remove_locks(self):
        """Xóa lock files để tránh "profile đang được dùng"""
        lock_files = ["SingletonLock", "SingletonSocket", "SingletonCookie"]
        for lock_name in lock_files:
            lock_file = self.profile_base_dir / lock_name
            try:
                if lock_file.exists():
                    lock_file.unlink()
                    logger.debug(f"🔓 Xóa {lock_name}")
            except Exception:
                pass

    def fix_crash_flag(self):
        """Fix flag "Crashed" trong Preferences để Edge không báo restore session"""
        prefs_file = self.profile_path / "Preferences"
        if not prefs_file.exists():
            return
        try:
            import json
            with prefs_file.open("r", encoding="utf-8") as f:
                prefs = json.load(f)
            if prefs.get("profile", {}).get("exit_type") == "Crashed":
                prefs["profile"]["exit_type"] = "Normal"
                with prefs_file.open("w", encoding="utf-8") as f:
                    json.dump(prefs, f)
                logger.debug("✅ Fix crash flag")
        except Exception:
            pass

    def get_profile_path(self) -> str:
        """Lấy đường dẫn profile"""
        return str(self.profile_base_dir)

    def set_startup_urls(self, urls: list):
        """📌 Đặt sẵn các trang cố định để Edge tự mở khi khởi động profile này.
        Ghi thẳng vào Preferences của profile (restore_on_startup=4 + startup_urls),
        chỉ áp dụng cho profile RIÊNG của bot — không đụng tới Edge cá nhân.

        Đây là lớp dự phòng ở mức Chromium: nếu bot code (main_script.py) tự
        mở tab theo Config.CHANNELS thì các trang đó vẫn ưu tiên hơn, nhưng nếu
        bạn tự mở profile này bằng tay (double-click Edge trỏ vào profile này)
        thì các trang trong `urls` vẫn tự mở sẵn.
        """
        if not urls:
            return
        try:
            import json
            self.profile_path.mkdir(parents=True, exist_ok=True)
            prefs_file = self.profile_path / "Preferences"
            prefs = {}
            if prefs_file.exists():
                try:
                    with prefs_file.open("r", encoding="utf-8") as f:
                        prefs = json.load(f)
                except Exception:
                    prefs = {}
            session = prefs.setdefault("session", {})
            session["restore_on_startup"] = 4  # 4 = mở danh sách URL chỉ định
            session["startup_urls"] = list(urls)
            with prefs_file.open("w", encoding="utf-8") as f:
                json.dump(prefs, f)
            logger.info(f"📌 Đã đặt {len(urls)} trang cố định để mở khi khởi động profile")
        except Exception as e:
            logger.debug(f"⚠️ Lỗi set startup urls (bỏ qua): {e}")