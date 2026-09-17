"""
system_metrics.py
-----------------
Live resource metrics for the current Windows computer, collected with the
Python standard library only:

  * CPU usage %   - sampled from the kernel via ctypes -> GetSystemTimes
  * Memory        - via ctypes -> GlobalMemoryStatusEx
  * Disk usage    - drives enumerated via GetLogicalDrives, sizes via shutil

Every function is defensive: on any failure it returns None / [] instead of
raising, so the web application can never crash because a metric is missing.
Testable pure helpers (_cpu_percent_from_times, _memory_from_status) are
split out so the parsing logic can be unit-tested without a real OS.
"""

import ctypes
import platform
import shutil
from ctypes import wintypes

_WINDOWS = platform.system().lower() == "windows"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def format_bytes(size: int | None) -> str:
    """Render a byte count as GB (or B when tiny/None)."""
    if not size:
        return "0 B"
    gb = size / (1024 ** 3)
    if gb < 1:
        return f"{round(size / 1024 ** 2, 1)} MB"
    return f"{round(gb, 1)} GB"


# ---------------------------------------------------------------------------
# CPU usage
# ---------------------------------------------------------------------------
class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32),
                ("dwHighDateTime", ctypes.c_uint32)]


def _system_times() -> tuple[int, int, int]:
    """Return (idle, kernel, user) kernel tick values (Windows FILETIME)."""
    if not _WINDOWS:
        raise OSError("CPU sampling is only available on Windows")
    idle = _FILETIME()
    kernel = _FILETIME()
    user = _FILETIME()
    result = ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
    )
    if not result:
        raise OSError("GetSystemTimes failed")

    def _to_int(ft: _FILETIME) -> int:
        return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

    return _to_int(idle), _to_int(kernel), _to_int(user)


def _cpu_percent_from_times(idle1, kernel1, user1, idle2, kernel2, user2) -> float | None:
    """Pure function: compute CPU usage % from two (idle, kernel, user) samples.

    On Windows the kernel time already includes idle time, so:
        busy = (kernel + user) - idle
        usage = busy / (kernel + user)
    """
    total_delta = (kernel2 - kernel1) + (user2 - user1)
    if total_delta <= 0:
        return None
    idle_delta = idle2 - idle1
    busy_delta = total_delta - idle_delta
    percent = max(0.0, min(100.0, (busy_delta / total_delta) * 100.0))
    return round(percent, 1)


def cpu_percent(sample_seconds: float = 0.6) -> float | None:
    """Sample overall CPU usage over a short interval (real measurement)."""
    if not _WINDOWS:
        return None
    try:
        idle1, kernel1, user1 = _system_times()
        import time
        time.sleep(max(0.1, sample_seconds))
        idle2, kernel2, user2 = _system_times()
        return _cpu_percent_from_times(idle1, kernel1, user1,
                                       idle2, kernel2, user2)
    except (OSError, AttributeError, ImportError):
        return None


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _memory_from_status(total_phys, avail_phys) -> dict:
    """Pure function: build the memory report from raw physical values."""
    used = total_phys - avail_phys
    percent = round((used / total_phys) * 100.0, 1) if total_phys else 0.0
    return {
        "total": total_phys,
        "used": used,
        "available": avail_phys,
        "percent": percent,
    }


def _read_memory_raw() -> tuple[int, int]:
    """Read raw (total_phys, avail_phys) bytes from the Windows API."""
    if not _WINDOWS:
        raise OSError("Memory reading is only available on Windows")
    status = _MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    result = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    if not result:
        raise OSError("GlobalMemoryStatusEx failed")
    return int(status.ullTotalPhys), int(status.ullAvailPhys)


def memory() -> dict | None:
    """Return real RAM totals: total / used / available / usage percent."""
    try:
        total, available = _read_memory_raw()
        return _memory_from_status(total, available)
    except (OSError, AttributeError, ImportError):
        return None


# ---------------------------------------------------------------------------
# Disk usage
# ---------------------------------------------------------------------------
def _drive_letters() -> list[str]:
    """Return present drive letters such as ['C:\\', 'D:\\']. Windows only."""
    if not _WINDOWS:
        return []
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    except (OSError, AttributeError):
        return []
    drives = []
    for index in range(26):
        if bitmask & (1 << index):
            drives.append(chr(65 + index) + "\\")
    return drives


def disk_usage() -> list[dict]:
    """Return a dict per drive: letter, used/free/total bytes, usage percent."""

    def _for(path: str) -> dict | None:
        try:
            usage = shutil.disk_usage(path)
        except (OSError, PermissionError):
            return None
        return {
            "drive": path,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": round((usage.used / usage.total) * 100.0, 1) if usage.total else 0.0,
        }

    results = []
    for drive in _drive_letters():
        info = _for(drive)
        if info:
            results.append(info)
    if not results and _WINDOWS:
        # Fallback: the drive that contains this application.
        import os
        info = _for(os.path.dirname(os.path.abspath(__file__))[:3])
        if info:
            results.append(info)
    return results