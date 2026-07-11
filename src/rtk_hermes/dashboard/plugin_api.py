"""RTK Stats Dashboard API — serves /api/plugins/rtk-stats/ endpoints.

Mounted by the Hermes dashboard host at `/api/plugins/rtk-stats/`.
Provides real-time token savings data to the dashboard frontend.
"""
import json
import os
import subprocess
import time
from pathlib import Path

def _get_hermes_home():
    """Get the Hermes home directory."""
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))

def _rtk_available():
    """Check if rtk binary is in PATH."""
    return subprocess.run(["rtk", "--version"], capture_output=True, text=True, timeout=5).returncode == 0

def _get_metrics():
    """Get current rtk-hermes metrics from the running Hermes process."""
    try:
        # Import from the plugin
        sys.path.insert(0, str(_get_hermes_home() / "hermes-agent/venv/Lib/site-packages"))
        from rtk_hermes import _metrics, _metrics_snapshot
        
        data = _metrics_snapshot()
        return {
            "status": "ok",
            "metrics": data,
            "rtk_available": _rtk_available(),
            "version": "1.0.0"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "rtk_available": _rtk_available(),
            "version": "1.0.0"
        }

def _get_rtk_stats():
    """Get RTK token savings from the rtk gain command."""
    try:
        result = subprocess.run(
            ["rtk", "gain"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return {
                "status": "ok",
                "output": result.stdout.strip(),
                "last_updated": time.time()
            }
        else:
            return {
                "status": "error",
                "error": result.stderr.strip() or f"Exit code: {result.returncode}",
                "last_updated": time.time()
            }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "error": "rtk gain timed out",
            "last_updated": time.time()
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "last_updated": time.time()
        }

def _get_top_filters():
    """Get the most used RTK filters from rtk gain output."""
    try:
        result = subprocess.run(
            ["rtk", "gain", "--json"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            # Parse the filters from the JSON output
            filters = data.get("filters", [])
            # Sort by count descending
            filters.sort(key=lambda x: x.get("count", 0), reverse=True)
            return {
                "status": "ok",
                "filters": filters[:10],  # Top 10
                "last_updated": time.time()
            }
        else:
            return {
                "status": "error",
                "error": "No filters found",
                "last_updated": time.time()
            }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "last_updated": time.time()
        }

# Endpoint handlers — these will be called by the dashboard host
ENDPOINTS = {
    "/api/plugins/rtk-stats/metrics": _get_metrics,
    "/api/plugins/rtk-stats/stats": _get_rtk_stats,
    "/api/plugins/rtk-stats/filters": _get_top_filters,
    "/api/plugins/rtk-stats/status": lambda: {
        "status": "ok",
        "rtk_available": _rtk_available(),
        "version": "1.0.0"
    }
}

def handle_request(path, method="GET"):
    """Handle incoming requests to RTK stats endpoints."""
    if path in ENDPOINTS:
        handler = ENDPOINTS[path]
        try:
            result = handler()
            return {
                "status": 200,
                "body": json.dumps(result, indent=2)
            }
        except Exception as e:
            return {
                "status": 500,
                "body": json.dumps({"status": "error", "error": str(e)})
            }
    else:
        return {
            "status": 404,
            "body": json.dumps({"status": "error", "error": "Not found"})
        }
