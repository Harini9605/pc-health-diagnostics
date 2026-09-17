# PC Health & System Diagnostics Tool

A self-contained **IT Support** web utility that reads **real** data straight
from a Windows PC and reports on its health - no fake or demo values, no
database, and no system modifications. Built for the portfolio with the
Python standard library plus Flask.

![Tech: Flask + ctypes + HTML/CSS/JS + pytest](https://img.shields.io/badge/Stack-Flask%20%2B%20stdlib%2Fctypes-464646)

---

## Overview

The tool turns a Windows computer into a one-page health report that an IT
Support engineer can open in any browser:

* A **dashboard** showing live CPU, memory, disk and network status.
* A one-click **full diagnostic pass** that scores each subsystem
  (**Healthy / Warning / Error**) and lists practical recommendations.
* A **printable report** ready to save as PDF for tickets or checklists.

Every number on the screen is collected from the real machine with
read-only system/library calls. The tool never runs user-supplied commands,
never deletes or changes anything, and never writes to a database.

---

## Features

* **System information** - real hostname, Windows version, Python version,
  architecture, processor, CPU core count, uptime (via `GetTickCount64`).
* **Live CPU usage (%)** - sampled from the kernel with ctypes
  (`GetSystemTimes`) over a short interval; pure math helper
  `_cpu_percent_from_times`.
* **Memory** - real total / used / available RAM and usage percent from
  `GlobalMemoryStatusEx`.
* **Disk health** - every present drive (letters from `GetLogicalDrives`,
  sizes via `shutil.disk_usage`) with usage meters and a
  **"High usage"** badge when a drive passes the warning threshold.
* **Network information** - local IPv4 (non-transmitting UDP trick),
  default gateway and adapter details parsed from real `ipconfig /all`
  output (line-based parser; MAC, IPv4, subnet mask, state).
* **Internet connectivity check** - a real, safe HTTP GET to Microsoft's
  official connectivity-test endpoint (the same one Windows NCSI uses),
  with response time; overridable via the `CONNECTIVITY_URL` environment
  variable.
* **Structured diagnostics** - thresholds table, per-check badges,
  overall verdict, and static, practical IT Support recommendations.
* **Print / save as PDF** report view with the system summary.
* **Security hardening** - CSRF tokens on every POST, fixed subprocess
  arguments (never user input), defensive collectors, styled
  400 / 404 / 500 error pages, no secrets exposed.

---

## Tech stack

| Layer      | Choice                                                                 |
|------------|------------------------------------------------------------------------|
| Language   | Python 3.10+ (developed on 3.14)                                       |
| Web        | Flask (only non-standard-library dependency)                           |
| System API | ctypes (`GetSystemTimes`, `GlobalMemoryStatusEx`, `GetLogicalDrives`)  |
| System CLI | `ipconfig /all` (read-only, fixed arguments, parsed output)            |
| HTTP check | `urllib` -> Microsoft connectivity-test endpoint                       |
| Frontend   | Jinja2 templates + Bootstrap 5 (CDN) + small custom CSS/JS            |
| Tests      | pytest (39 tests, all system calls and network mocked)                 |
| Database   | **None** - the last report is kept in memory and resets on restart     |

---

## Project structure

```
pc-health-diagnostics/
├── app.py                 # Flask app: routes, CSRF, error handlers
├── system_info.py         # hostname / OS / uptime (read-only)
├── system_metrics.py      # CPU %, memory, disk usage (ctypes + shutil)
├── network_info.py        # local IP, ipconfig parsing, connectivity check
├── diagnostics.py         # thresholds, evaluators, run_diagnostics()
├── templates/
│   ├── base.html          # navbar, flash messages
│   ├── dashboard.html     # live status page
│   ├── diagnostics.html   # report view + run prompt
│   └── error.html         # 400 / 404 / 500 pages
├── static/
│   ├── css/style.css      # custom styling (health dots, cards, badges)
│   └── js/main.js         # minor UI helpers
├── tests/
│   ├── conftest.py        # fixtures + a deterministic sample report
│   └── test_app.py        # 39 tests (collectors, diagnostics, routes)
├── requirements.txt       # Flask>=3.0.0
├── requirements-dev.txt   # + pytest>=8.0.0
├── pytest.ini
└── .gitignore
```

### Data flow

```
browser ──> app.py route
              │
              ├─ system_info.collect()          read-only OS queries
              ├─ metrics.cpu_percent()          GetSystemTimes sample
              ├─ metrics.memory()               GlobalMemoryStatusEx
              ├─ metrics.disk_usage()           GetLogicalDrives + shutil
              ├─ netinfo.local_ipv4()           UDP connect (no data sent)
              ├─ netinfo.adapter_list()         ipconfig /all (parsed)
              └─ netinfo.connectivity_status()  HTTP GET to msftconnecttest
                      │
                      └─ diagnostics.run_diagnostics() -> verdict + advice
```

---

## Installation

```powershell
# 1. Clone / copy the folder
cd pc-health-diagnostics

# 2. (Recommended) create a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Developer dependencies (tests)
pip install -r requirements-dev.txt
```

> Note: `requirements.txt` only contains Flask - everything else is the
> Python standard library (ctypes, shutil, socket, urllib, subprocess).

---

## How to run

```powershell
python app.py
```

Then open **http://127.0.0.1:5000** in a browser.

| Page          | URL                     | Purpose                                   |
|---------------|-------------------------|-------------------------------------------|
| Dashboard     | `http://127.0.0.1:5000/`| Live system report with all metrics       |
| Diagnostics   | `/diagnostics`          | Run / view the full diagnostic report     |
| Health        | `/health`               | Simple JSON "ok" endpoint                 |

Optional environment variables:

* `SECRET_KEY` - Flask session signing key (set a random one in production).
* `CONNECTIVITY_URL` - override the connectivity-check endpoint.

---

## How diagnostics work

`diagnostics.run_diagnostics()` collects each subsystem and scores it against
a threshold table:

| Check               | Warning threshold | Error threshold | Recommendation when bad               |
|---------------------|-------------------|-----------------|---------------------------------------|
| CPU usage           | >= 70%            | >= 90%          | close heavy apps, check Task Manager  |
| Memory usage        | >= 80%            | >= 92%          | close browser tabs / apps, restart    |
| Disk usage (per drive) | >= 80%         | >= 92%          | Disk Cleanup, move / delete files     |
| Network connectivity| offline           | offline         | check adapter, ipconfig /release+renew|

Each metric becomes a *check* with a **Healthy / Warning / Error** badge and
an optional recommendation. The overall verdict is the worst status found.
The engine performs **only reads** - it never modifies the system.

---

## Example IT Support use cases

1. **"The PC is running slowly"** - open the dashboard, read CPU and memory
   percentages, check the diagnosis page for which subsystem is critical and
   follow the printed recommendation (Task Manager, heavy apps, restart).
2. **"My internet stopped working"** - run Diagnostics; the network check
   tests real connectivity and the recommendation guides you through
   checking the adapter, `ipconfig` configuration and the cable / Wi-Fi.
3. **"The system drive is full"** - the dashboard flags the drive with a
   **High usage** badge; the report's disk recommendation points to Disk
   Cleanup and removing large files.
4. **Before a ticket hand-off** - run Diagnostics once, use
   **Print / Save as PDF** and attach the report showing which component is
   in a Warning or Error state.

---

## Testing

```powershell
python -m pytest tests -v
```

The suite contains **39 tests** and never modifies the real system:

* **System info** - real hostname collected, uptime text formatting.
* **CPU** - pure `_cpu_percent_from_times` math, two-sample collection with
  the kernel call mocked, failure -> `None`.
* **Memory** - pure `_memory_from_status`, raw-value read mocked.
* **Disk** - drive enumeration and `shutil.disk_usage` mocked; inaccessible
  drives are skipped.
* **Network** - a canned `ipconfig /all` sample is parsed correctly, the
  fixed command-line is asserted (never user input), the local-IP and
  connectivity checks are tested with mocks including online / HTTP-error /
  URLError / timeout paths.
* **Diagnostics engine** - threshold boundaries, healthy and error overall
  verdicts, missing collectors handled without crashing.
* **Web routes** - dashboard renders real and missing metrics, the
  diagnostics flow (prompt -> POST -> report) works end to end, CSRF is
  required on POST, and the 404 page renders.

Corner cases covered: empty ipconfig output, no drives, per-drive failures,
collector exceptions, and offline connectivity with the associated
recommendation text.

---

## Limitations

* The `ipconfig` parser expects **English** Windows output (standard on US /
  international English systems). Non-English locales may return an empty
  adapter list - the app degrades gracefully, never crashes.
* It is a **local** tool: run it on the machine you want to inspect (or
  inside a diagnostic session). It is not a remote monitoring agent.
* Connectivity checks need an allowlisted network; if your environment
  blocks the default endpoint a captive-working alternative can be set via
  `CONNECTIVITY_URL`.
* The last report lives in memory only - restarting the server clears it
  (a deliberate choice: nothing is persisted, so there is no database).
* The HTTPS variant of the connectivity endpoint may fail behind proxies
  that MITM TLS; the plain-HTTP Microsoft endpoint is used by default.

---

## License / notes

Sample portfolio project - real data, safe reads, no system changes.