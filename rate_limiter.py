"""
⏱️ RATE LIMITER & ANTI-BAN SYSTEM (v4.1)
- RateLimiter: delay chỉ khi thực sự cần
- CircuitBreaker: ngừng submit tạm nếu lỗi liên tiếp
"""

import time
import asyncio
from typing import Dict
from logger_setup import logger


class CircuitBreaker:
    """
    Ngừng submit tạm thời nếu lỗi liên tiếp vượt ngưỡng.

    Trạng thái:
      CLOSED   → bình thường, cho phép tất cả request
      OPEN     → đang chặn, từ chối request (đợi recovery_time)
      HALF_OPEN→ thử 1 request; nếu thành công → CLOSED, nếu thất bại → OPEN lại

    Dùng:
        breaker = CircuitBreaker(failure_threshold=5, recovery_time=300)
        try:
            result = await breaker.call(my_coroutine())
        except CircuitOpenError:
            logger.warning("Circuit đang OPEN, bỏ qua")
    """

    class CircuitOpenError(Exception):
        pass

    def __init__(self, failure_threshold: int = 5, recovery_time: float = 300.0,
                 label: str = ""):
        self.failure_threshold = failure_threshold
        self.recovery_time     = recovery_time
        self.label             = label or "circuit"
        self.failure_count     = 0
        self.last_failure_time = 0.0
        self.state             = "CLOSED"   # CLOSED | OPEN | HALF_OPEN

    def _try_recover(self):
        if self.state == "OPEN":
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.recovery_time:
                self.state = "HALF_OPEN"
                logger.warning(f"🔁 [{self.label}] Circuit → HALF_OPEN (thử lại)")

    async def call(self, coro):
        self._try_recover()

        if self.state == "OPEN":
            wait = self.recovery_time - (time.time() - self.last_failure_time)
            raise CircuitBreaker.CircuitOpenError(
                f"[{self.label}] Circuit OPEN — retry sau {wait:.0f}s"
            )

        try:
            result = await coro
            # Thành công → reset
            if self.state == "HALF_OPEN":
                logger.info(f"✅ [{self.label}] Circuit → CLOSED (recovered)")
            self.failure_count = 0
            self.state = "CLOSED"
            return result

        except CircuitBreaker.CircuitOpenError:
            raise
        except Exception as exc:
            self.failure_count    += 1
            self.last_failure_time = time.time()
            if self.state == "HALF_OPEN" or self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                logger.error(
                    f"🔴 [{self.label}] Circuit → OPEN "
                    f"(lỗi #{self.failure_count}, chờ {self.recovery_time:.0f}s)"
                )
            raise exc

    @property
    def is_open(self) -> bool:
        self._try_recover()
        return self.state == "OPEN"

    def reset(self):
        """Reset thủ công — dùng khi biết lỗi đã được fix."""
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = "CLOSED"
        logger.info(f"🔄 [{self.label}] Circuit reset → CLOSED")

    def __repr__(self):
        return (f"CircuitBreaker(label={self.label!r}, state={self.state}, "
                f"failures={self.failure_count}/{self.failure_threshold})")


class RateLimiter:
    """Rate limiter tối giản - chỉ delay khi cần thiết"""

    def __init__(self, min_delay: float = 0.5, requests_per_minute: int = 30):
        self.min_delay = min_delay
        self.requests_per_minute = requests_per_minute
        self.last_request: Dict[str, float] = {}
        self.request_times: Dict[str, list] = {}

    async def wait_if_needed(self, account: str) -> float:
        now = time.time()

        # Delay tối thiểu giữa 2 request
        last = self.last_request.get(account)
        if last is not None:
            elapsed = now - last
            if elapsed < self.min_delay:
                await asyncio.sleep(self.min_delay - elapsed)
                now = time.time()

        # Rate limit per minute
        history = self.request_times.setdefault(account, [])
        cutoff = now - 60
        # Xóa các entry cũ
        while history and history[0] < cutoff:
            history.pop(0)

        if len(history) >= self.requests_per_minute:
            wait = history[0] + 60 - now
            if wait > 0:
                logger.warning(f"⏱️ Rate limit [{account}]: chờ {wait:.1f}s")
                await asyncio.sleep(wait)
                now = time.time()

        self.last_request[account] = now
        history.append(now)
        return now

    def get_remaining_time(self, account: str) -> float:
        if account not in self.last_request:
            return 0.0
        return max(0.0, self.min_delay - (time.time() - self.last_request[account]))

    def get_stats(self, account: str) -> dict:
        history = self.request_times.get(account, [])
        now = time.time()
        recent = sum(1 for t in history if t > now - 60)
        return {
            "requests_last_minute": recent,
            "remaining_time": self.get_remaining_time(account),
            "utilization": f"{(recent / self.requests_per_minute * 100):.1f}%",
        }


class AntiDetectionManager:
    """Anti-detection tối giản - chỉ rate limit, không delay random vô ích"""

    def __init__(self):
        self.rate_limiter = RateLimiter(min_delay=0.5, requests_per_minute=30)

    async def apply_all_protections(self, account: str):
        """Chỉ enforce rate limit, không thêm delay ngẫu nhiên làm chậm bot"""
        await self.rate_limiter.wait_if_needed(account)

    def print_stats(self):
        logger.info("\n" + "="*70)
        logger.info("🛡️ ANTI-DETECTION STATS:")
        for account in self.rate_limiter.last_request:
            stats = self.rate_limiter.get_stats(account)
            logger.info(
                f"  [{account}] {stats['requests_last_minute']}/{self.rate_limiter.requests_per_minute} req/min "
                f"({stats['utilization']}) | wait: {stats['remaining_time']:.2f}s"
            )
        logger.info("="*70 + "\n")


_anti_detection = None

def init_anti_detection() -> AntiDetectionManager:
    global _anti_detection
    _anti_detection = AntiDetectionManager()
    logger.info("✅ Anti-Detection khởi tạo xong (v4.0)")
    return _anti_detection

def get_anti_detection() -> AntiDetectionManager:
    global _anti_detection
    if _anti_detection is None:
        _anti_detection = init_anti_detection()
    return _anti_detection