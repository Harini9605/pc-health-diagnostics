"""
diagnostics.py
--------------
Evaluates real system metrics and returns structured health checks.

Each collector (CPU, RAM, disk, network) is called through the sibling
modules and assessed against a threshold table. The engine never performs
system modifications - it only produces status text and recommendations.

Tests can exercise the pure evaluators directly and patch the collectors
for end-to-end tests without touching a real OS.
"""

from datetime import datetime

import network_info as netinfo
import system_metrics as metrics


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
_CPU_WARN   = 70.0
_CPU_ERR    = 90.0
_MEM_WARN   = 80.0
_MEM_ERR    = 92.0
_DISK_WARN  = 80.0
_DISK_ERR   = 92.0


# ---------------------------------------------------------------------------
# Recommendation text (static, practical, for IT Support use)
# ---------------------------------------------------------------------------
_RECS = {
    "cpu_warning": (
        "High CPU usage. Open Task Manager (Ctrl+Shift+Esc) to identify "
        "resource-heavy applications. Close unnecessary programs, check for "
        "Windows Update or antivirus scans running in the background."
    ),
    "cpu_error": (
        "Critical CPU load. Close heavy applications immediately. Open "
        "Task Manager and end non-essential processes. Check Task Manager "
        "startup tab for unwanted programs. Scan for malware."
    ),
    "mem_warning": (
        "High memory usage. Close unnecessary applications and browser "
        "tabs. Restart the PC to release cached memory and improve "
        "responsiveness."
    ),
    "mem_error": (
        "Critical memory usage. Close memory-heavy applications (browser "
        "tabs, databases, VMs) immediately. Consider upgrading physical "
        "RAM if this persists after reboots."
    ),
    "disk_warning": (
        "Disk usage is high. Remove temporary and unnecessary files "
        "(run Disk Cleanup, clear the Recycle Bin, and delete old "
        "downloads). Move large files to another drive."
    ),
    "disk_error": (
        "Disk is nearly full. A full system drive can destabilise Windows "
        "and cause crashes. Delete large/unneeded files or move them to "
        "another drive. Run Disk Cleanup as administrator."
    ),
    "network_error": (
        "No internet connectivity. Check that the network adapter is "
        "enabled (Control Panel -> Network Connections). Run "
        "ipconfig in a Command Prompt to verify IP configuration. "
        "Check the physical cable or Wi-Fi connection, then try "
        "ipconfig /release and ipconfig /renew. Ping the default "
        "gateway to verify local network reachability."
    ),
}


# ---------------------------------------------------------------------------
# Pure evaluators (easily unit-tested)
# ---------------------------------------------------------------------------
def evaluate_cpu(percent: float | None) -> dict:
    """Return a single health-check dict for CPU usage."""
    if percent is None:
        return {"name": "CPU usage", "status": "error",
                "value": "Not available",
                "recommendation": "Could not sample CPU usage on this system."}
    if percent >= _CPU_ERR:
        return {"name": "CPU usage", "status": "error",
                "value": f"{percent}%",
                "recommendation": _RECS["cpu_error"]}
    if percent >= _CPU_WARN:
        return {"name": "CPU usage", "status": "warning",
                "value": f"{percent}%",
                "recommendation": _RECS["cpu_warning"]}
    return {"name": "CPU usage", "status": "healthy",
            "value": f"{percent}%",
            "recommendation": ""}


def evaluate_memory(percent: float | None) -> dict:
    if percent is None:
        return {"name": "Memory usage", "status": "error",
                "value": "Not available",
                "recommendation": "Could not read memory information."}
    if percent >= _MEM_ERR:
        return {"name": "Memory usage", "status": "error",
                "value": f"{percent}%",
                "recommendation": _RECS["mem_error"]}
    if percent >= _MEM_WARN:
        return {"name": "Memory usage", "status": "warning",
                "value": f"{percent}%",
                "recommendation": _RECS["mem_warning"]}
    return {"name": "Memory usage", "status": "healthy",
            "value": f"{percent}%",
            "recommendation": ""}


def evaluate_disk(usage_pct: float | None, drive: str = "") -> dict:
    label = f"Disk usage ({drive})" if drive else "Disk usage"
    if usage_pct is None:
        return {"name": label, "status": "error",
                "value": "Not available",
                "recommendation": "Could not read disk information."}
    if usage_pct >= _DISK_ERR:
        return {"name": label, "status": "error",
                "value": f"{usage_pct}%",
                "recommendation": _RECS["disk_error"]}
    if usage_pct >= _DISK_WARN:
        return {"name": label, "status": "warning",
                "value": f"{usage_pct}%",
                "recommendation": _RECS["disk_warning"]}
    return {"name": label, "status": "healthy",
            "value": f"{usage_pct}%",
            "recommendation": ""}


def evaluate_connectivity(status: str, response_ms: int | None = None) -> dict:
    ms_text = f" ({response_ms} ms)" if response_ms is not None else ""
    if status == "online":
        return {"name": "Network connectivity", "status": "healthy",
                "value": f"Online{ms_text}",
                "recommendation": ""}
    return {"name": "Network connectivity", "status": "error",
            "value": f"Offline{ms_text}",
            "recommendation": _RECS["network_error"]}


# ---------------------------------------------------------------------------
# Run diagnostics (uses real collectors)
# ---------------------------------------------------------------------------
_SEVERITY_RANK = {"healthy": 0, "warning": 1, "error": 2}


def _worst(items: list[dict]) -> str:
    """Return 'healthy', 'warning' or 'error' (the worst among a set)."""
    if not items:
        return "healthy"
    return max(items, key=lambda c: _SEVERITY_RANK.get(c["status"], 0))["status"]


def run_diagnostics(sample_seconds: float = 0.6,
                    connectivity_url: str | None = None) -> dict:
    """Perform a full diagnostic pass using real system collectors.

    Returns a structured dict with all individual checks and an
    overall severity level.
    """
    checks: list[dict] = []

    # CPU
    cpu_pct = metrics.cpu_percent(sample_seconds)
    checks.append(evaluate_cpu(cpu_pct))

    # Memory
    mem = metrics.memory()
    checks.append(evaluate_memory(mem["percent"] if mem else None))

    # Disk (one check per drive)
    disks = metrics.disk_usage()
    for drive_info in disks:
        checks.append(evaluate_disk(drive_info["percent"], drive_info["drive"]))
    if not disks:
        checks.append({"name": "Disk usage", "status": "error",
                        "value": "No drives found",
                        "recommendation": "No accessible disk drives were detected."})

    # Network connectivity
    conn = netinfo.connectivity_status(url=connectivity_url)
    checks.append(evaluate_connectivity(conn["status"], conn.get("response_ms")))

    overall = _worst(checks)
    recommendations = [c["recommendation"] for c in checks if c["recommendation"]]

    return {
        "run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "checks": checks,
        "overall": overall,
        "overall_label": overall.capitalize(),
        "recommendations": recommendations,
    }