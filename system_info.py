"""
system_info.py
--------------
Static information about the host computer. Every value is read from the
real machine - no placeholders, no sample data.

  * hostname            - the computer name (socket.gethostname)
  * windows version     - from platform.win32_ver / platform.platform
  * Python version      - from platform.python_version
  * system architecture - from platform.machine / platform.architecture
  * processor           - from platform.processor / PROCESSOR_IDENTIFIER
  * system uptime       - from the kernel tick counter (GetTickCount64)
"""

import os
import platform
import socket
import time
from datetime import datetime

_WINDOWS = platform.system().lower() == "windows"


def uptime_seconds() -> int | None:
    """Seconds since the operating system booted (Windows tick counter).

    Returns None when the value cannot be read (e.g. non-Windows host).
    """
    if not _WINDOWS:
        return None
    try:
        import ctypes
        millis = ctypes.windll.kernel32.GetTickCount64()
        return int(millis // 1000)
    except (AttributeError, OSError, ImportError):
        return None


def uptime_text(seconds: int | None) -> str:
    """Human-readable uptime such as "2d 5h 13m" (or a fallback)."""
    if not seconds:
        return "Not available"
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def _windows_version() -> str:
    """Return something like 'Windows 11 (Version 10.0.22631)'."""
    try:
        release, version, _csd, _ptype = platform.win32_ver()
        if release:
            label = f"Windows {release}"
            if version:
                label += f" (Version {version})"
            return label
    except Exception:
        pass
    return platform.platform() or "Unknown"


def _processor_name() -> str:
    """Best-effort processor name (platform may return an empty string)."""
    name = platform.processor()
    if name:
        return name
    return os.environ.get("PROCESSOR_IDENTIFIER", "Unknown")


def collect() -> dict:
    """Gather and return a dictionary of real host information."""
    uptime = uptime_seconds()
    return {
        "hostname": socket.gethostname(),
        "windows_version": _windows_version(),
        "python_version": platform.python_version(),
        "architecture": f"{platform.machine()} ({platform.architecture()[0]})",
        "processor": _processor_name(),
        "cpu_cores": os.cpu_count(),
        "uptime_seconds": uptime,
        "uptime": uptime_text(uptime),
        "timezone": time.tzname[0] if time.daylight else time.tzname[0],
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }