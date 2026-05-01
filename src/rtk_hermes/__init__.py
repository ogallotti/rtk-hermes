"""
RTK Rewrite Plugin for Hermes

Transparently rewrites terminal tool commands to RTK equivalents
before execution, achieving 60-90% LLM token savings.

All rewrite logic lives in `rtk rewrite` (src/discover/registry.rs).
This plugin is a thin delegate — to add or change rules, edit the
Rust registry, not this file.

Installation:
    pip install rtk-hermes

The plugin auto-registers via the hermes_agent.plugins entry point.
No manual configuration needed — just install and restart Hermes.

RTK Exit Code Protocol (rtk rewrite):
    0 — Rewrite allowed (auto-allow)
    1 — No RTK equivalent (passthrough)
    2 — Deny rule matched
    3 — Ask rule matched (rewrite exists, needs confirmation)
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Optional

__version__ = "1.1.0"

logger = logging.getLogger(__name__)

_rtk_available: Optional[bool] = None

# Exit codes from `rtk rewrite` that indicate a successful rewrite.
# 0 = auto-allow, 3 = ask rule (rewrite produced, awaiting confirmation).
# See: https://github.com/rtk-ai/rtk docs/contributing/EXIT_CODES.md
_RTK_OK_CODES = frozenset({0, 3})


def _check_rtk() -> bool:
    """Check if rtk binary is available in PATH. Result is cached."""
    global _rtk_available
    if _rtk_available is not None:
        return _rtk_available
    _rtk_available = shutil.which("rtk") is not None
    return _rtk_available


def _try_rewrite(command: str) -> Optional[str]:
    """Delegate to ``rtk rewrite`` and return the rewritten command, or None.

    Accepts RTK exit codes 0 (auto-allow) and 3 (ask rule) as successful
    rewrites.  Both produce valid rewritten output on stdout.

    Returns *None* when RTK is unavailable, times out, or has no rewrite.
    """
    try:
        result = subprocess.run(
            ["rtk", "rewrite", command],
            capture_output=True,
            text=True,
            timeout=2,
        )
        rewritten = result.stdout.strip()

        if result.returncode in _RTK_OK_CODES and rewritten and rewritten != command:
            return rewritten

        # Log unexpected exit codes (not 0, 1, 2, 3) for diagnostics.
        if result.returncode not in (0, 1, 2, 3):
            stderr = result.stderr.strip()
            logger.warning(
                "[rtk] unexpected exit code %d for %r%s",
                result.returncode,
                command,
                f": {stderr}" if stderr else "",
            )

        return None
    except subprocess.TimeoutExpired:
        logger.debug("[rtk] rewrite timed out for %r", command)
        return None
    except (FileNotFoundError, OSError) as exc:
        logger.debug("[rtk] rewrite failed for %r: %s", command, exc)
        return None


def _pre_tool_call(*, tool_name: str, args: dict, task_id: str, **_kwargs) -> None:
    """pre_tool_call hook: rewrite terminal commands to use RTK.

    Mutates ``args["command"]`` in-place when RTK provides a rewrite.
    The dict is mutable, so changes propagate to the caller without
    needing a return value.
    """
    if tool_name != "terminal":
        return

    command = args.get("command")
    if not isinstance(command, str) or not command:
        return

    rewritten = _try_rewrite(command)
    if rewritten:
        logger.info("[rtk] %s -> %s", command, rewritten)
        args["command"] = rewritten


def register(ctx) -> None:
    """Entry point called by Hermes plugin system."""
    if not _check_rtk():
        logger.warning("[rtk] rtk binary not found in PATH — plugin disabled")
        return

    ctx.register_hook("pre_tool_call", _pre_tool_call)
    logger.info("[rtk] Hermes plugin registered")
