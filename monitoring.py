"""
📊 MONITORING & HEALTH SYSTEM (v4.1)
- HealthMonitor: CPU/RAM check mỗi 120s
- PerformanceMonitor: thống kê task duration
- SubmissionMetrics: thống kê code/giờ, success rate, cảnh báo khi degraded
"""

import asyncio
import time
import psutil
from collections import defaultdict
from typing import Dict, List
from logger_setup import logger


class HealthMonitor:
    """Giám sát CPU/RAM - nhẹ, không block event loop"""

    def __init__(self, check_interval: int = 120):
        self.check_interval = check_interval
        self.is_running = False
        self.cpu_threshold = 85.0
        self.memory_threshold = 85.0

    async def _get_metrics_async(self) -> dict:
        """Lấy metrics trong thread pool để không block event loop"""
        loop = asyncio.get_running_loop()
        def _get():
            mem = psutil.virtual_memory()
            return {
                "cpu": psutil.cpu_percent(interval=0.5),
                "memory_pct": mem.percent,
                "memory_mb": mem.used // (1024 * 1024),
            }
        return await loop.run_in_executor(None, _get)

    async def start(self):
        self.is_running = True
        logger.info(f"🏥 Health Monitor bắt đầu (interval={self.check_interval}s)")
        while self.is_running:
            try:
                metrics = await self._get_metrics_async()
                warnings = []
                if metrics["cpu"] > self.cpu_threshold:
                    warnings.append(f"CPU cao: {metrics['cpu']:.1f}%")
                if metrics["memory_pct"] > self.memory_threshold:
                    warnings.append(f"RAM cao: {metrics['memory_pct']:.1f}% ({metrics['memory_mb']}MB)")
                for w in warnings:
                    logger.warning(f"⚠️ {w}")
            except Exception as e:
                logger.debug(f"⚠️ Health check lỗi: {e}")
            await asyncio.sleep(self.check_interval)

    def stop(self):
        self.is_running = False

    def get_current_metrics(self) -> dict:
        """Sync version - chỉ dùng khi không có event loop"""
        try:
            mem = psutil.virtual_memory()
            return {
                "cpu": psutil.cpu_percent(interval=0.2),
                "memory_pct": mem.percent,
                "memory_mb": mem.used // (1024 * 1024),
            }
        except Exception:
            return {"cpu": 0, "memory_pct": 0, "memory_mb": 0}


class PerformanceMonitor:
    """Giám sát performance - giới hạn history để không tốn RAM"""

    MAX_HISTORY = 500

    def __init__(self):
        self.task_times: Dict[str, List[float]] = {}
        self.task_success: Dict[str, int] = {}
        self.task_failed: Dict[str, int] = {}

    def record_task(self, task_name: str, duration: float, success: bool = True):
        times = self.task_times.setdefault(task_name, [])
        times.append(duration)
        # Giới hạn history
        if len(times) > self.MAX_HISTORY:
            self.task_times[task_name] = times[-self.MAX_HISTORY:]

        if success:
            self.task_success[task_name] = self.task_success.get(task_name, 0) + 1
        else:
            self.task_failed[task_name] = self.task_failed.get(task_name, 0) + 1

    def get_task_stats(self, task_name: str) -> dict:
        times = self.task_times.get(task_name, [])
        if not times:
            return {}
        s = self.task_success.get(task_name, 0)
        f = self.task_failed.get(task_name, 0)
        total = s + f
        return {
            "task_name": task_name,
            "total": total,
            "success": s,
            "failed": f,
            "avg_duration": sum(times) / len(times),
            "min_duration": min(times),
            "max_duration": max(times),
            "success_rate": (s / total * 100) if total > 0 else 0,
        }

    def print_stats(self):
        if not self.task_times:
            logger.info("ℹ️ Không có performance data")
            return
        logger.info("\n" + "="*70)
        logger.info("⚡ PERFORMANCE STATS:")
        for name in self.task_times:
            st = self.get_task_stats(name)
            logger.info(
                f"  {name}: ✅{st['success']} ❌{st['failed']} "
                f"| avg={st['avg_duration']:.2f}s | rate={st['success_rate']:.1f}%"
            )
        logger.info("="*70 + "\n")


class SubmissionMetrics:
    """
    Thống kê submit theo thời gian thực.
    - Đếm code/giờ, success/fail, loại lỗi
    - Cảnh báo khi error rate > ERROR_RATE_THRESHOLD trong cửa sổ gần nhất
    - Dùng sliding window 1 giờ (không tốn RAM)

    Dùng:
        metrics = SubmissionMetrics()
        metrics.record("SUCCESS")
        metrics.record("FAILED", error_type="TIMEOUT")
        await metrics.alert_if_degraded()
    """

    ERROR_RATE_THRESHOLD = 0.30   # >30% fail → cảnh báo
    WINDOW_SECONDS       = 3600   # cửa sổ 1 giờ
    MAX_EVENTS           = 2000   # tránh tốn RAM

    def __init__(self):
        # Mỗi entry: (timestamp, status, error_type)
        self._events: list = []
        self._error_by_type: Dict[str, int] = defaultdict(int)
        self._alerted = False

    def record(self, status: str, error_type: str = ""):
        """Ghi 1 lần submit. status = 'SUCCESS' | 'FAILED' | 'SKIP' | ..."""
        now = time.time()
        self._events.append((now, status, error_type))
        if error_type:
            self._error_by_type[error_type] += 1
        # Giữ list gọn
        if len(self._events) > self.MAX_EVENTS:
            self._events = self._events[-self.MAX_EVENTS:]

    def _window_events(self):
        """Chỉ lấy events trong cửa sổ gần nhất."""
        cutoff = time.time() - self.WINDOW_SECONDS
        return [(ts, st, et) for ts, st, et in self._events if ts >= cutoff]

    def stats(self) -> dict:
        """Trả về dict thống kê 1 giờ gần nhất."""
        events = self._window_events()
        total   = len(events)
        success = sum(1 for _, st, _ in events if st == "SUCCESS")
        failed  = sum(1 for _, st, _ in events if st == "FAILED")
        rate    = (success / total * 100) if total else 0.0
        return {
            "window_hours": self.WINDOW_SECONDS / 3600,
            "total":        total,
            "success":      success,
            "failed":       failed,
            "success_rate": round(rate, 1),
            "codes_per_hour": total,
            "error_by_type": dict(self._error_by_type),
        }

    async def alert_if_degraded(self):
        """Gọi định kỳ — cảnh báo nếu error rate vượt ngưỡng."""
        events = self._window_events()
        if len(events) < 5:
            return   # Chưa đủ dữ liệu

        failed = sum(1 for _, st, _ in events if st == "FAILED")
        rate   = failed / len(events)

        if rate > self.ERROR_RATE_THRESHOLD:
            if not self._alerted:
                logger.error(
                    f"🚨 [METRICS] Error rate cao: {rate*100:.1f}% "
                    f"({failed}/{len(events)} lần trong {self.WINDOW_SECONDS//60} phút) "
                    f"— vượt ngưỡng {self.ERROR_RATE_THRESHOLD*100:.0f}%"
                )
                self._alerted = True
        else:
            self._alerted = False   # Reset alert khi ổn lại

    def log_summary(self):
        """Log tóm tắt — gọi trong heartbeat hoặc cuối ngày."""
        st = self.stats()
        logger.info(
            f"📊 [METRICS] {st['window_hours']:.0f}h: "
            f"✅{st['success']} ❌{st['failed']} / {st['total']} | "
            f"rate={st['success_rate']}% | {st['codes_per_hour']} codes/h"
        )
        if st["error_by_type"]:
            for etype, cnt in sorted(st["error_by_type"].items(), key=lambda x: -x[1]):
                logger.info(f"   ↳ {etype}: {cnt}x")


# Global instances
_health_monitor = None
_perf_monitor   = None
_sub_metrics    = None


def init_monitoring():
    global _health_monitor, _perf_monitor, _sub_metrics
    _health_monitor = HealthMonitor(check_interval=120)
    _perf_monitor   = PerformanceMonitor()
    _sub_metrics    = SubmissionMetrics()
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_health_monitor.start())
    except RuntimeError:
        pass
    logger.info("✅ Monitoring khởi tạo xong (v4.1 + SubmissionMetrics)")
    return _health_monitor, _perf_monitor, _sub_metrics


def get_health_monitor() -> HealthMonitor:
    global _health_monitor
    if _health_monitor is None:
        init_monitoring()
    return _health_monitor


def get_performance_monitor() -> PerformanceMonitor:
    global _perf_monitor
    if _perf_monitor is None:
        init_monitoring()
    return _perf_monitor


def get_submission_metrics() -> SubmissionMetrics:
    global _sub_metrics
    if _sub_metrics is None:
        init_monitoring()
    return _sub_metrics