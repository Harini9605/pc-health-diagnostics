"""
Pytest fixtures for the PC Health & System Diagnostics Tool.

This suite NEVER modifies the real Windows system:
    * no files are created/deleted outside the Python temp directory,
    * system commands and connectivity checks are mocked,
    * collectors that touch the OS are patched in tests that need a
      deterministic result.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app as flask_app  # noqa: E402


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, SECRET_KEY="test-secret-key")
    # Each test starts with no stored diagnostics report.
    flask_app._last_report = None
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def csrf(client):
    """Return (and create if needed) the session CSRF token."""

    def _get():
        with client.session_transaction() as sess:
            if not sess.get("_csrf_token"):
                sess["_csrf_token"] = "test-csrf-token"
            return sess["_csrf_token"]

    return _get


SAMPLE_REPORT = {
    "run_at": "2026-01-01 12:00:00",
    "checks": [
        {"name": "CPU usage", "status": "healthy", "value": "20.0%", "recommendation": ""},
        {"name": "Memory usage", "status": "warning", "value": "85.0%",
         "recommendation": "High memory usage. Close unnecessary applications."},
        {"name": "Disk usage (C:\\)", "status": "healthy", "value": "40.0%", "recommendation": ""},
        {"name": "Network connectivity", "status": "healthy", "value": "Online (20 ms)",
         "recommendation": ""},
    ],
    "overall": "warning",
    "overall_label": "Warning",
    "recommendations": ["High memory usage. Close unnecessary applications."],
}


@pytest.fixture
def sample_report():
    return dict(SAMPLE_REPORT)