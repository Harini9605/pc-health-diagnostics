"""
app.py
------
PC Health & System Diagnostics Tool
=====================================

A self-contained IT Support Engineer diagnostic utility built with Flask.

    * Collects real hardware information directly from the Windows PC.
    * Shows live CPU, RAM, disk and network status on a dashboard.
    * Runs a structured diagnostic check and reports health/warnings/errors
      with practical IT Support recommendations.
    * Never executes user-supplied commands and never modifies the system.

Run locally:
    python app.py
    then open http://127.0.0.1:5000
"""

import os
import secrets
from datetime import datetime

from flask import (Flask, abort, flash, redirect, render_template,
                   request, session, url_for)

import diagnostics
import network_info as netinfo
import system_info
import system_metrics as metrics

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "pc-health-dev-key-change-in-production"
)

# Template filter: 1234567890 -> "1.1 GB"
app.jinja_env.filters["format_bytes"] = metrics.format_bytes

# Store the last diagnostics report in memory (no database required;
# resets when the server restarts).
_last_report: dict | None = None


# ---------------------------------------------------------------------------
# Context processor - shared values for every template
# ---------------------------------------------------------------------------
@app.context_processor
def inject_globals():
    return {
        "app_name": "PC Health",
        "current_year": datetime.now().year,
    }


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------
def _get_csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["_csrf_token"] = token
    return token


app.jinja_env.globals["csrf_token"] = _get_csrf_token


@app.before_request
def csrf_protect():
    if request.method == "POST":
        stored = session.get("_csrf_token")
        incoming = request.form.get("csrf_token")
        if not stored or not incoming or not secrets.compare_digest(stored, incoming):
            abort(400, description="Invalid or missing CSRF token.")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def _safe(fn, *a, **kw):
    """Call a collector function, return its result or None on failure."""
    try:
        return fn(*a, **kw)
    except Exception:
        return None


@app.route("/")
def dashboard():
    """Main IT Support dashboard showing all live metrics."""
    info = system_info.collect()
    cpu = _safe(metrics.cpu_percent, 0.2)
    mem = _safe(metrics.memory)
    disks = _safe(metrics.disk_usage) or []
    ipv4 = _safe(netinfo.local_ipv4)
    gateway = _safe(netinfo.default_gateway)
    adapters = _safe(netinfo.adapter_list) or []
    conn = _safe(netinfo.connectivity_status) or {
        "status": "offline", "response_ms": None,
        "detail": "Could not check", "host_checked": "",
    }
    overall = (_last_report or {}).get("overall", "not-run")

    return render_template(
        "dashboard.html",
        info=info,
        cpu=cpu,
        mem=mem,
        disks=disks,
        ipv4=ipv4,
        gateway=gateway,
        adapters=adapters,
        conn=conn,
        overall=overall,
    )


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------
@app.route("/diagnostics")
def diagnostics_page():
    """Show the last diagnostics report, or prompt the user to run one."""
    global _last_report
    return render_template(
        "diagnostics.html",
        report=_last_report,
        info=system_info.collect(),
    )


@app.route("/diagnostics/run", methods=["POST"])
def run_diagnostics():
    """Run a full diagnostic pass using real system collectors."""
    global _last_report
    _last_report = diagnostics.run_diagnostics(sample_seconds=0.2)
    flash(f"Diagnostics completed at {_last_report['run_at']}.", "success")
    return redirect(url_for("diagnostics_page"))


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------
@app.route("/health")
def health():
    return {"status": "ok", "tool": "PC Health & System Diagnostics"}


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(400)
def bad_request(_e):
    return render_template("error.html", code=400,
                           title="Bad request",
                           message="The request was invalid (e.g. a missing security token)."), 400


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404,
                           title="Page not found",
                           message="The page you are looking for does not exist."), 404


@app.errorhandler(500)
def server_error(_e):
    return render_template("error.html", code=500,
                           title="Server error",
                           message="Something went wrong internally. Please try again."), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)