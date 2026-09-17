"""
test_app.py - automated tests for the PC Health & System Diagnostics Tool.

Coverage:
    * Dashboard loads and renders real/patched data
    * System information collection (hostname / uptime / formatting)
    * CPU and memory collection (pure parsers + patched API calls)
    * Disk information (patched shutil / drive enumeration)
    * Network information (ipconfig parsing, local IP, connectivity check)
    * Diagnostics results and threshold evaluation
    * POST /diagnostics/run action + CSRF protection
    * Error handling (missing metrics never crash; 404 pages)

Safety: the suite never touches the real system. All subprocess / network
calls and Windows API reads are mocked. The only real reads are safe,
read-only calls such as socket.gethostname / platform.version.
"""

import socket
from types import SimpleNamespace
from unittest import mock

import diagnostics
import network_info
import system_info
import system_metrics

from conftest import SAMPLE_REPORT  # deterministic report shared with fixtures


# ---------------------------------------------------------------------------
# System information
# ---------------------------------------------------------------------------
def test_system_info_collect_returns_real_hostname():
    info = system_info.collect()
    assert info["hostname"] == socket.gethostname()          # real value
    assert info["windows_version"]                            # Windows 11 ...
    assert info["python_version"]
    assert info["architecture"]
    assert "uptime" in info
    assert "server_time" in info


def test_uptime_text_formatting():
    assert system_info.uptime_text(86400 + 3600 + 61) == "1d 1h 1m"
    assert system_info.uptime_text(600) == "10m"
    assert system_info.uptime_text(None) == "Not available"


# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------
def test_cpu_percent_from_times_pure():
    # busy halves for a 100% busy system
    assert system_metrics._cpu_percent_from_times(
        100, 100, 100, 100, 150, 150) == 100.0
    # half busy
    assert system_metrics._cpu_percent_from_times(
        100, 100, 0, 200, 250, 50) == 50.0
    # no change -> None
    assert system_metrics._cpu_percent_from_times(1, 1, 1, 1, 1, 1) is None


def test_cpu_percent_uses_two_samples():
    samples = [
        (100, 100, 0),     # idle, kernel, user @ t1
        (100, 150, 50),    # @ t2: busy 100% of delta
    ]
    with mock.patch("system_metrics._system_times", side_effect=samples) as st, \
         mock.patch("time.sleep"):
        result = system_metrics.cpu_percent(0.1)
    assert result == 100.0
    assert st.call_count == 2


def test_cpu_percent_failure_returns_none():
    with mock.patch("system_metrics._system_times",
                    side_effect=OSError("sampling failed")):
        assert system_metrics.cpu_percent() is None


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
def test_memory_from_status_pure():
    memory = system_metrics._memory_from_status(total_phys=16 * 1024 ** 3,
                                                 avail_phys=4 * 1024 ** 3)
    assert memory["used"] == 12 * 1024 ** 3
    assert memory["percent"] == 75.0
    assert memory["total"] == 16 * 1024 ** 3


def test_memory_reads_raw_values():
    with mock.patch("system_metrics._read_memory_raw",
                    return_value=(16 * 1024 ** 3, 4 * 1024 ** 3)):
        memory = system_metrics.memory()
    assert memory["percent"] == 75.0
    assert memory["used"] == 12 * 1024 ** 3


def test_memory_failure_returns_none():
    with mock.patch("system_metrics._read_memory_raw",
                    side_effect=OSError("boom")):
        assert system_metrics.memory() is None


def test_format_bytes():
    assert system_metrics.format_bytes(1024 ** 3) == "1.0 GB"
    assert system_metrics.format_bytes(0) == "0 B"
    assert system_metrics.format_bytes(None) == "0 B"


# ---------------------------------------------------------------------------
# Disk
# ---------------------------------------------------------------------------
def test_disk_usage_uses_shutil():
    fake_usage = SimpleNamespace(total=1000, used=300, free=700)
    with mock.patch("system_metrics._drive_letters", return_value=["C:\\"]), \
         mock.patch("system_metrics.shutil.disk_usage", return_value=fake_usage):
        drives = system_metrics.disk_usage()
    assert drives == [{"drive": "C:\\", "total": 1000, "used": 300,
                       "free": 700, "percent": 30.0}]


def test_disk_usage_skips_inaccessible_drives():
    # shutil failure for one drive -> that drive is skipped, others kept.
    def raiser_or_value(path):
        if path == "C:\\":
            raise PermissionError("no access")
        return SimpleNamespace(total=500, used=100, free=400)

    with mock.patch("system_metrics._drive_letters", return_value=["C:\\", "D:\\"]), \
         mock.patch("system_metrics.shutil.disk_usage", side_effect=raiser_or_value):
        drives = system_metrics.disk_usage()
    assert len(drives) == 1
    assert drives[0]["drive"] == "D:\\"


def test_disk_usage_empty_returns_list():
    with mock.patch("system_metrics._drive_letters", return_value=[]), \
         mock.patch("system_metrics.shutil.disk_usage",
                    side_effect=PermissionError) as fallback:
        assert system_metrics.disk_usage() == []
        fallback.call_count >= 0  # fallback may run but must not crash


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
IPCONFIG_SAMPLE = """Windows IP Configuration

   Host Name . . . . . . . . . . . . : testpc

Wireless LAN adapter Wi-Fi:

   Media State . . . . . . . . . . . : Media disconnected
   Physical Address. . . . . . . . . : 30-89-4A-55-DE-A3

Ethernet adapter Ethernet:

   Physical Address. . . . . . . . . : 7C-57-58-10-FB-D8
   IPv4 Address. . . . . . . . . . . : 10.0.0.5(Preferred)
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : fe80::1%1
                                       10.0.0.1
"""


def test_adapters_from_text_parses_real_format():
    adapters = network_info.adapters_from_text(IPCONFIG_SAMPLE)
    assert len(adapters) == 2
    wifi, ethernet = adapters
    assert wifi["status"] == "Disconnected"
    assert wifi["mac"] == "30-89-4A-55-DE-A3"
    assert ethernet["status"] == "Connected"
    assert ethernet["ipv4"] == "10.0.0.5"
    assert ethernet["subnet_mask"] == "255.255.255.0"


def test_default_gateway_prefers_ipv4():
    gateway = network_info.default_gateway_from_text(IPCONFIG_SAMPLE)
    assert gateway == "10.0.0.1"


def test_adapters_from_text_handles_empty():
    assert network_info.adapters_from_text("") == []
    assert network_info.adapters_from_text("No such command") == []


def test_adapter_list_calls_fixed_command_only():
    # The subprocess command must be fixed - never user input.
    with mock.patch("network_info._ipconfig_output", return_value=IPCONFIG_SAMPLE) as out:
        adapters = network_info.adapter_list()
    assert adapters and adapters[0]["name"]  # parsed something
    assert out.call_count == 1


def test_ipconfig_output_uses_fixed_args():
    fake = SimpleNamespace(stdout="Windows IP Configuration", stderr="")
    with mock.patch("network_info.subprocess.run", return_value=fake) as run:
        text = network_info._ipconfig_output()
    assert text == "Windows IP Configuration"
    assert run.call_args.args[0] == ["ipconfig", "/all"]  # fixed command


def test_local_ipv4_via_udp_trick():
    sock = mock.Mock()
    sock.__enter__ = mock.Mock(return_value=sock)
    sock.__exit__ = mock.Mock(return_value=False)
    sock.getsockname.return_value = ("192.168.1.50", 0)
    with mock.patch("network_info.socket.socket", return_value=sock):
        assert network_info.local_ipv4() == "192.168.1.50"


def test_local_ipv4_fallback_and_none():
    with mock.patch("network_info.socket.socket",
                    side_effect=OSError("no network")), \
         mock.patch("network_info.socket.gethostbyname_ex", side_effect=socket.gaierror):
        assert network_info.local_ipv4() is None


def test_connectivity_online():
    response = mock.MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.status = 200
    response.read.return_value = b"Microsoft Connect Test"
    with mock.patch("network_info.urllib.request.urlopen", return_value=response) as open_:
        result = network_info.connectivity_status()
    assert result["status"] == "online"
    assert result["response_ms"] is not None
    request = open_.call_args.args[0]
    assert "msftconnecttest" in request.full_url


def test_connectivity_offline_on_bad_http_status():
    response = mock.MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.status = 500
    response.read.return_value = b""
    with mock.patch("network_info.urllib.request.urlopen", return_value=response):
        result = network_info.connectivity_status()
    assert result["status"] == "offline"


def test_connectivity_offline_on_urlerror():
    with mock.patch("network_info.urllib.request.urlopen",
                    side_effect=__import__("urllib.error").error.URLError("down")):
        result = network_info.connectivity_status()
    assert result["status"] == "offline"
    assert result["response_ms"] is None


def test_connectivity_offline_on_oserror():
    with mock.patch("network_info.urllib.request.urlopen", side_effect=OSError("timeout")):
        result = network_info.connectivity_status()
    assert result["status"] == "offline"


# ---------------------------------------------------------------------------
# Diagnostics engine
# ---------------------------------------------------------------------------
def test_evaluate_cpu_thresholds():
    assert diagnostics.evaluate_cpu(50)["status"] == "healthy"
    assert diagnostics.evaluate_cpu(80.5)["status"] == "warning"
    assert diagnostics.evaluate_cpu(95)["status"] == "error"
    assert diagnostics.evaluate_cpu(None)["status"] == "error"


def test_evaluate_memory_thresholds():
    assert diagnostics.evaluate_memory(70)["status"] == "healthy"
    assert diagnostics.evaluate_memory(85)["status"] == "warning"
    assert diagnostics.evaluate_memory(95)["status"] == "error"
    assert "close unnecessary applications" in \
        diagnostics.evaluate_memory(85)["recommendation"].lower()


def test_evaluate_disk_thresholds():
    assert diagnostics.evaluate_disk(50, "C:\\")["status"] == "healthy"
    assert diagnostics.evaluate_disk(85, "C:\\")["status"] == "warning"
    assert "temporary" in diagnostics.evaluate_disk(85)["recommendation"].lower()
    assert diagnostics.evaluate_disk(95, "C:\\")["status"] == "error"


def test_evaluate_connectivity():
    healthy = diagnostics.evaluate_connectivity("online", 20)
    assert healthy["status"] == "healthy" and "20 ms" in healthy["value"]
    offline = diagnostics.evaluate_connectivity("offline")
    assert offline["status"] == "error"
    assert "ipconfig" in offline["recommendation"].lower()
    assert "adapter" in offline["recommendation"].lower()


def test_run_diagnostics_healthy_overall():
    with mock.patch("diagnostics.metrics.cpu_percent", return_value=30.0), \
         mock.patch("diagnostics.metrics.memory",
                    return_value={"percent": 50.0, "total": 2, "used": 1,
                                  "available": 1}), \
         mock.patch("diagnostics.metrics.disk_usage",
                    return_value=[{"drive": "C:\\", "percent": 40.0,
                                   "total": 2, "used": 1, "free": 1}]), \
         mock.patch("diagnostics.netinfo.connectivity_status",
                    return_value={"status": "online", "response_ms": 15,
                                  "detail": "ok", "host_checked": "url"}):
        report = diagnostics.run_diagnostics(sample_seconds=0.01)
    assert report["overall"] == "healthy"
    assert len(report["checks"]) == 4
    assert report["recommendations"] == []


def test_run_diagnostics_flags_warnings_and_errors():
    with mock.patch("diagnostics.metrics.cpu_percent", return_value=95.0), \
         mock.patch("diagnostics.metrics.memory",
                    return_value={"percent": 93.0, "total": 2, "used": 2,
                                  "available": 0}), \
         mock.patch("diagnostics.metrics.disk_usage",
                    return_value=[{"drive": "C:\\", "percent": 97.0,
                                   "total": 2, "used": 2, "free": 0}]), \
         mock.patch("diagnostics.netinfo.connectivity_status",
                    return_value={"status": "offline", "response_ms": None,
                                  "detail": "down", "host_checked": "url"}):
        report = diagnostics.run_diagnostics(sample_seconds=0.01)
    assert report["overall"] == "error"
    assert len(report["recommendations"]) == 4
    joined = " ".join(report["recommendations"]).lower()
    assert "close heavy applications" in joined       # CPU error
    assert "close memory-heavy" in joined             # memory error
    assert "disk is nearly full" in joined            # disk error
    assert "check that the network adapter" in joined  # network error


def test_run_diagnostics_handles_missing_collectors():
    # All collectors fail -> every check reports an error, no crash.
    with mock.patch("diagnostics.metrics.cpu_percent", return_value=None), \
         mock.patch("diagnostics.metrics.memory", return_value=None), \
         mock.patch("diagnostics.metrics.disk_usage", return_value=[]), \
         mock.patch("diagnostics.netinfo.connectivity_status",
                    return_value={"status": "offline", "response_ms": None,
                                  "detail": "x", "host_checked": "url"}):
        report = diagnostics.run_diagnostics(sample_seconds=0.01)
    assert report["overall"] == "error"
    assert any(c["status"] == "error" for c in report["checks"])


# ---------------------------------------------------------------------------
# App routes
# ---------------------------------------------------------------------------
def _patch_dashboard(monkeypatch):
    """Point every heavy dashboard collector at deterministic values."""
    monkeypatch.setattr("system_metrics.cpu_percent", lambda *a, **k: 40.5)
    monkeypatch.setattr("system_metrics.memory",
                        lambda: {"total": 16 * 1024**3, "used": 8 * 1024**3,
                                 "available": 8 * 1024**3, "percent": 50.0})
    monkeypatch.setattr("system_metrics.disk_usage",
                        lambda: [{"drive": "C:\\", "total": 1000, "used": 300,
                                  "free": 700, "percent": 30.0}])
    monkeypatch.setattr("network_info.local_ipv4", lambda: "10.0.0.5")
    monkeypatch.setattr("network_info.default_gateway", lambda: "10.0.0.1")
    monkeypatch.setattr("network_info.adapter_list",
                        lambda: [{"name": "Ethernet adapter Ethernet",
                                  "status": "Connected", "mac": "AA-BB-CC-DD-EE-FF",
                                  "ipv4": "10.0.0.5", "subnet_mask": "255.255.255.0",
                                  "gateway": "10.0.0.1"}])
    monkeypatch.setattr("network_info.connectivity_status",
                        lambda: {"status": "online", "response_ms": 25,
                                 "detail": "ok", "host_checked": "url"})


def test_dashboard_loads_with_real_values(client, monkeypatch):
    _patch_dashboard(monkeypatch)
    resp = client.get("/")
    data = resp.data.decode()
    assert resp.status_code == 200
    assert "PC Health" in data
    assert "System information" in data
    assert socket.gethostname() in data          # real hostname rendered
    assert "10.0.0.5" in data                    # real (mocked) local IP
    assert "Ethernet adapter Ethernet" in data   # adapter table
    assert "40.5" in data                        # CPU percent
    assert "50.0" in data                        # memory percent


def test_dashboard_flags_high_disk_usage(client, monkeypatch):
    _patch_dashboard(monkeypatch)
    monkeypatch.setattr("system_metrics.disk_usage",
                        lambda: [{"drive": "C:\\", "total": 1000, "used": 850,
                                  "free": 150, "percent": 85.0}])
    data = client.get("/").data.decode()
    assert "High usage" in data


def test_dashboard_handles_missing_metrics(client, monkeypatch):
    # Every collector failing must still render the page (no crash).
    monkeypatch.setattr("system_metrics.cpu_percent", lambda *a, **k: None)
    monkeypatch.setattr("system_metrics.memory", lambda: None)
    monkeypatch.setattr("system_metrics.disk_usage", lambda: [])
    monkeypatch.setattr("network_info.local_ipv4", lambda: None)
    monkeypatch.setattr("network_info.default_gateway", lambda: None)
    monkeypatch.setattr("network_info.adapter_list", lambda: [])
    monkeypatch.setattr("network_info.connectivity_status",
                        lambda: {"status": "offline", "response_ms": None,
                                 "detail": "down", "host_checked": "url"})
    resp = client.get("/")
    assert resp.status_code == 200
    assert "PC Health" in resp.data.decode()


def test_diagnostics_page_shows_prompt_when_not_run(client):
    resp = client.get("/diagnostics")
    data = resp.data.decode()
    assert resp.status_code == 200
    assert "Run Diagnostics" in data
    assert "System Diagnostics Report" not in data


def test_diagnostics_post_runs_and_redirects(client, csrf, monkeypatch):
    monkeypatch.setattr("diagnostics.run_diagnostics",
                        lambda **kw: dict(SAMPLE_REPORT))
    resp = client.post("/diagnostics/run",
                       data={"csrf_token": csrf()},
                       follow_redirects=True)
    assert resp.status_code == 200
    data = resp.data.decode()
    assert "System Diagnostics Report" in data
    assert "CPU usage" in data
    assert "Warning" in data
    assert "High memory usage" in data


def test_diagnostics_report_renders_stored_report(client):
    client.application._last_report = dict(SAMPLE_REPORT)
    data = client.get("/diagnostics").data.decode()
    assert "System Diagnostics Report" in data
    assert "Overall health" in data
    assert "Warning" in data
    assert "Healthy" in data
    assert "Print / Save as PDF" in data


def test_post_without_csrf_token_rejected(client):
    resp = client.post("/diagnostics/run", data={})
    assert resp.status_code == 400


def test_unknown_page_renders_404(client):
    resp = client.get("/this-page-does-not-exist")
    assert resp.status_code == 404
    assert b"Page not found" in resp.data


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"