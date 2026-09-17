"""
network_info.py
---------------
Network diagnostics data collected from the real Windows computer:

  * Local IP address          - via a non-transmitting UDP connect trick
  * Default gateway           - from ipconfig /all output
  * Network adapter details   - parsed from ipconfig /all
  * Internet connectivity     - safe real HTTP request to Microsoft's
                                official connectivity-test endpoint

No subprocess receives user-controlled input. Every call is defensive
and returns a safe fallback on failure.
"""

import os
import platform
import re
import socket
import subprocess
import time
import urllib.request

_WINDOWS = platform.system().lower() == "windows"

# Microsoft's official connectivity-test page (same endpoint the Windows
# Network Connectivity Status Indicator uses). The plain-HTTP variant is
# preferred because some networks / proxies block TLS to it.
_CONNECTIVITY_URL = os.environ.get(
    "CONNECTIVITY_URL",
    "http://www.msftconnecttest.com/connecttest.txt",
)


# ---------------------------------------------------------------------------
# Local IP
# ---------------------------------------------------------------------------
def local_ipv4() -> str | None:
    """Return the local IPv4 address that this computer would use to
    reach an external host.  This is purely informational; the UDP
    socket never transmits any data.
    """
    for target_host in ("8.8.8.8", "1.1.1.1"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(1)
                sock.connect((target_host, 80))
                return sock.getsockname()[0]
        except OSError:
            continue
    # Final fallback: gethostbyname approach.
    try:
        return socket.gethostbyname_ex(socket.gethostname())[2][0]
    except socket.gaierror:
        return None


# ---------------------------------------------------------------------------
# ipconfig parsing
# ---------------------------------------------------------------------------
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ipconfig_output(timeout: float = 6) -> str | None:
    """Run ipconfig /all and return the raw text (English locale expected)."""
    if not _WINDOWS:
        return None
    try:
        proc = subprocess.run(
            ["ipconfig", "/all"],
            capture_output=True, text=True, timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        return proc.stdout or proc.stderr
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


def adapters_from_text(text: str) -> list[dict]:
    """Parse ipconfig /all text into a list of adapter dicts.

    Each dict: {name, status, mac, ipv4, subnet_mask, gateway}.

    Works on English Windows output; never raises.  Parsing is line-based
    because ipconfig separates adapter headers and field lines with blank
    lines, which defeats block splitting.
    """
    if not text:
        return []

    _RE_HEADER = re.compile(
        r"^\s*([A-Za-z0-9 .\-()]+(?:adapter|Adapter)[^:]*):\s*$", re.IGNORECASE
    )
    # Field lines look like:  "IPv4 Address . . . . . : 10.0.0.5(Preferred)"
    _RE_FIELD = re.compile(r"^\s*([^:]+?)\s*[.\s]*:\s*(.*)$")
    _RE_MAC   = re.compile(r"[0-9A-Fa-f]{2}([-:][0-9A-Fa-f]{2}){5}")

    KEY_MAP = {
        "media state":      "status",
        "physical address": "mac",
        "ipv4 address":     "ipv4",
        "subnet mask":      "subnet_mask",
        "default gateway":  "gateway",
    }

    adapters: list[dict] = []
    current: dict | None = None

    for line in text.splitlines():
        header = _RE_HEADER.match(line)
        if header:
            current = {"name": header.group(1).strip(), "status": "Unknown",
                       "mac": "", "ipv4": "", "subnet_mask": "", "gateway": ""}
            adapters.append(current)
            continue

        if current is None:
            continue

        field = _RE_FIELD.match(line)
        if not field:
            continue
        label = field.group(1).strip().rstrip(".").lower()
        raw_value = field.group(2).strip()
        # Strip Windows suffixes such as "(Preferred)".
        value = re.split(r"\s*\(", raw_value)[0].strip()

        for key_fragment, field_name in KEY_MAP.items():
            if key_fragment in label:
                if field_name == "status":
                    current["status"] = (
                        "Disconnected"
                        if "disconnect" in raw_value.lower()
                        else "Connected"
                    )
                elif field_name == "mac":
                    mac_match = _RE_MAC.search(value)
                    current["mac"] = mac_match.group(0) if mac_match else value
                elif value:
                    current[field_name] = value
                break

    for adapter in adapters:
        # A connected adapter often has no "Media State" line but does have
        # a MAC address - classify it as Connected instead of Unknown.
        if adapter["status"] == "Unknown" and (adapter["ipv4"] or adapter["mac"]):
            adapter["status"] = "Connected"

    return adapters


def default_gateway_from_text(text: str) -> str | None:
    """Return the default gateway (IPv4 preferred) from ipconfig output.

    Handles the multi-line gateway entries ipconfig prints (an IPv6
    link-local first, then the IPv4 gateway on a continuation line).
    """
    gateways: list[str] = []
    raw_lines = text.splitlines()
    for index, line in enumerate(raw_lines):
        if "Default Gateway" not in line or ":" not in line:
            continue
        first = line.split(":", 1)[1].strip()
        if first:
            first = first.split("(")[0].strip().split()[0]
            if first and (first[0].isdigit() or ":" in first):
                gateways.append(first)
        # Continuation lines hold extra gateways (e.g. the IPv4 one).
        for extra in raw_lines[index + 1:index + 4]:
            token = extra.strip()
            if not token or " (" in token:
                continue
            if re.fullmatch(r"[0-9a-fA-F:.%]+", token) and ("." in token or ":" in token):
                gateways.append(token)
                break
    for gateway in gateways:  # prefer an IPv4-looking address
        if "." in gateway and ":" not in gateway:
            return gateway
    return gateways[0] if gateways else None


def default_gateway() -> str | None:
    """Best-effort default gateway from real ipconfig output."""
    output = _ipconfig_output()
    return default_gateway_from_text(output) if output else None


def adapter_list() -> list[dict]:
    """Return real adapter information (or empty list on failure)."""
    output = _ipconfig_output()
    return adapters_from_text(output) if output else []


# ---------------------------------------------------------------------------
# Connectivity check (safe, real HTTP)
# ---------------------------------------------------------------------------
def connectivity_status(url: str | None = None, timeout: float = 5) -> dict:
    """Perform a real, safe HTTP request and measure connectivity.

    Default target: Microsoft's official connectivity-test page.  The
    request is a simple HTTP(S) GET; no commands are executed.

    Returns:
        {"status": "online"|"offline",
         "response_ms": int|None,
         "detail": str,
         "host_checked": str}
    """
    url = url or _CONNECTIVITY_URL
    host_checked = url
    start = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PC-Health-Diagnostics/1.0"})
        with urllib.request.urlopen(req, timeout=max(1, timeout)) as resp:
            data = resp.read()
            elapsed = round((time.monotonic() - start) * 1000)
            ok = resp.status == 200 and len(data) > 0
            return {
                "status": "online" if ok else "offline",
                "response_ms": elapsed,
                "detail": f"Connected (HTTP {resp.status})" if ok
                          else f"Unexpected HTTP status {resp.status}",
                "host_checked": host_checked,
            }
    except urllib.error.URLError:
        return {
            "status": "offline",
            "response_ms": None,
            "detail": "No internet connection",
            "host_checked": host_checked,
        }
    except (OSError, socket.timeout):
        return {
            "status": "offline",
            "response_ms": None,
            "detail": "Network timed out",
            "host_checked": host_checked,
        }
    except Exception:
        return {
            "status": "offline",
            "response_ms": None,
            "detail": "Connectivity check failed",
            "host_checked": host_checked,
        }