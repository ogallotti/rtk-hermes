"""
RTK Rewrite Plugin for Hermes.

This plugin rewrites Hermes `terminal` tool commands to their RTK equivalents
before execution. It is intentionally conservative: all rewrite logic stays in
`rtk rewrite`, failures are fail-open, and no post-tool output compaction is
performed by default.

Installation:
    "$HOME/.hermes/hermes-agent/venv/bin/python" -m pip install rtk-hermes

The plugin is discovered via the `hermes_agent.plugins` entry point. Enable it
by adding `rtk-rewrite` to `plugins.enabled` in `~/.hermes/config.yaml`, then
restart Hermes or start a new session.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from typing import Optional

__version__ = "1.2.3"

logger = logging.getLogger(__name__)

_rtk_available: Optional[bool] = None

# `rtk rewrite` exit codes:
# 0 = rewrite allowed, 1 = no equivalent, 2 = deny, 3 = ask/confirm.
# Codes 0 and 3 both include a valid rewritten command on stdout.
_RTK_REWRITE_OK_CODES = frozenset({0, 3})
_RTK_REWRITE_KNOWN_CODES = frozenset({0, 1, 2, 3})
_MODE_VALUES = frozenset({"rewrite", "suggest", "off"})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_DEFAULT_TIMEOUT_MS = 2_000


@dataclass(frozen=True)
class RtkHermesConfig:
    """Runtime config read from environment variables."""

    mode: str = "rewrite"
    timeout_ms: int = _DEFAULT_TIMEOUT_MS
    preview_marker: bool = True
    enabled_backends: tuple[str, ...] = ("local",)


@dataclass
class RtkHermesMetrics:
    """In-process counters. Commands are never stored to avoid leaking secrets."""

    attempted: int = 0
    rewritten: int = 0
    suggested: int = 0
    no_equivalent: int = 0
    denied: int = 0
    same_command: int = 0
    timeouts: int = 0
    errors: int = 0
    unexpected_exit_codes: int = 0
    missing_rtk: int = 0
    skipped_backend: int = 0
    total_rewrite_ms: float = 0.0

    @property
    def average_rewrite_ms(self) -> float:
        if self.attempted <= 0:
            return 0.0
        return round(self.total_rewrite_ms / self.attempted, 2)


_metrics = RtkHermesMetrics()


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    logger.warning("[rtk] invalid boolean value %r; using %s", value, default)
    return default


def _parse_timeout_ms(value: str | None) -> int:
    if value is None:
        return _DEFAULT_TIMEOUT_MS
    try:
        timeout = int(value)
    except ValueError:
        logger.warning("[rtk] invalid RTK_HERMES_TIMEOUT_MS=%r; using %sms", value, _DEFAULT_TIMEOUT_MS)
        return _DEFAULT_TIMEOUT_MS
    if timeout <= 0:
        logger.warning("[rtk] RTK_HERMES_TIMEOUT_MS must be > 0; using %sms", _DEFAULT_TIMEOUT_MS)
        return _DEFAULT_TIMEOUT_MS
    return timeout


def _parse_enabled_backends(value: str | None) -> tuple[str, ...]:
    """Parse RTK_HERMES_BACKENDS.

    Defaults to local only. A rewrite happens before Hermes dispatches the
    terminal command, so `rtk` must exist in the execution backend too. SSH,
    Docker and remote sandboxes are therefore opt-in.
    """
    raw = (value or "local").strip().lower()
    if not raw:
        return ("local",)
    parts = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not parts:
        return ("local",)
    if "all" in parts:
        return ("all",)
    return parts


def _load_config() -> RtkHermesConfig:
    mode = os.getenv("RTK_HERMES_MODE", "rewrite").strip().lower()
    if mode not in _MODE_VALUES:
        logger.warning("[rtk] invalid RTK_HERMES_MODE=%r; using 'rewrite'", mode)
        mode = "rewrite"
    return RtkHermesConfig(
        mode=mode,
        timeout_ms=_parse_timeout_ms(os.getenv("RTK_HERMES_TIMEOUT_MS")),
        preview_marker=_parse_bool(os.getenv("RTK_HERMES_PREVIEW_MARKER"), default=True),
        enabled_backends=_parse_enabled_backends(os.getenv("RTK_HERMES_BACKENDS")),
    )


def _check_rtk(*, refresh: bool = False) -> bool:
    """Check if the rtk binary is available in PATH. Result is cached."""
    global _rtk_available
    if refresh:
        _rtk_available = None
    if _rtk_available is not None:
        return _rtk_available
    _rtk_available = shutil.which("rtk") is not None
    if not _rtk_available:
        _metrics.missing_rtk += 1
    return _rtk_available


def _with_preview_marker(command: str, *, enabled: bool) -> str:
    """Add a visible RTK marker to Hermes terminal previews without changing behavior."""
    if not enabled:
        return command
    stripped = command.lstrip()
    if stripped.startswith(": RTK && "):
        return command
    return f": RTK && {command}"


def _current_terminal_backend(args: dict | None = None) -> str:
    """Return the active Hermes terminal backend name."""
    args = args or {}
    for key in ("env_type", "backend"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return (
        os.getenv("TERMINAL_ENV")
        or os.getenv("TERMINAL_BACKEND")
        or "local"
    ).strip().lower() or "local"


def _backend_enabled(backend: str, config: RtkHermesConfig) -> bool:
    enabled = config.enabled_backends
    return "all" in enabled or backend in enabled


def _try_rewrite(command: str, *, config: RtkHermesConfig | None = None) -> Optional[str]:
    """Delegate to `rtk rewrite` and return the rewritten command, or None."""
    cfg = config or _load_config()
    started = time.perf_counter()
    _metrics.attempted += 1
    try:
        result = subprocess.run(
            ["rtk", "rewrite", command],
            capture_output=True,
            text=True,
            timeout=cfg.timeout_ms / 1000,
        )
        rewritten = result.stdout.strip()
        if result.returncode in _RTK_REWRITE_OK_CODES and rewritten and rewritten != command:
            return rewritten
        if result.returncode == 1:
            _metrics.no_equivalent += 1
        elif result.returncode == 2:
            _metrics.denied += 1
        elif result.returncode in _RTK_REWRITE_OK_CODES and rewritten == command:
            _metrics.same_command += 1
        elif result.returncode not in _RTK_REWRITE_KNOWN_CODES:
            _metrics.unexpected_exit_codes += 1
            logger.warning(
                "[rtk] unexpected `rtk rewrite` exit code %s%s",
                result.returncode,
                "; stderr redacted" if result.stderr.strip() else "",
            )
        return None
    except subprocess.TimeoutExpired:
        _metrics.timeouts += 1
        logger.debug("[rtk] rewrite timed out")
        return None
    except (FileNotFoundError, OSError):
        _metrics.errors += 1
        logger.debug("[rtk] rewrite failed")
        return None
    finally:
        _metrics.total_rewrite_ms += (time.perf_counter() - started) * 1000


def _pre_tool_call(*, tool_name: str, args: dict, task_id: str = "", **_kwargs) -> None:
    """pre_tool_call hook: rewrite terminal commands to use RTK.

    Mutates ``args["command"]`` in-place when RTK provides a rewrite. The dict
    is mutable, so changes propagate to the caller without needing a return
    value.
    """
    if tool_name != "terminal":
        return

    cfg = _load_config()
    if cfg.mode == "off":
        return

    backend = _current_terminal_backend(args)
    if not _backend_enabled(backend, cfg):
        _metrics.skipped_backend += 1
        logger.debug("[rtk] rewrite skipped for terminal backend %s", backend)
        return

    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        return

    stripped = command.lstrip()
    if stripped.startswith("rtk ") or stripped.startswith(": RTK && "):
        return

    rewritten = _try_rewrite(command, config=cfg)
    if not rewritten:
        return

    logger.debug("[rtk] rewrite candidate accepted")
    if cfg.mode == "suggest":
        _metrics.suggested += 1
        logger.info("[rtk] rewrite suggestion available")
        return

    args["command"] = _with_preview_marker(rewritten, enabled=cfg.preview_marker)
    _metrics.rewritten += 1


def _metrics_snapshot() -> dict:
    data = asdict(_metrics)
    data["average_rewrite_ms"] = _metrics.average_rewrite_ms
    return data


def _reset_metrics() -> None:
    global _metrics
    _metrics = RtkHermesMetrics()


def _handle_command(raw_args: str = "") -> str:
    """Slash command handler for `/rtk`. Returns JSON for easy inspection."""
    args = (raw_args or "").strip().split()
    subcommand = args[0] if args else "status"

    if subcommand in {"status", "show"}:
        return json.dumps(
            {
                "version": __version__,
                "rtk_available": _check_rtk(refresh=True),
                "config": asdict(_load_config()),
                "metrics": _metrics_snapshot(),
            },
            ensure_ascii=False,
            indent=2,
        )
    if subcommand in {"stats", "metrics"}:
        return json.dumps(_metrics_snapshot(), ensure_ascii=False, indent=2)
    if subcommand in {"reset-stats", "reset-metrics"}:
        _reset_metrics()
        return "RTK Hermes metrics reset."
    if subcommand in {"config", "env"}:
        return json.dumps(
            {
                "env": {
                    "RTK_HERMES_MODE": "rewrite | suggest | off",
                    "RTK_HERMES_TIMEOUT_MS": f"integer milliseconds; default {_DEFAULT_TIMEOUT_MS}",
                    "RTK_HERMES_PREVIEW_MARKER": "true | false; default true",
                    "RTK_HERMES_BACKENDS": "comma-separated Hermes terminal backends; default local; use all to opt into every backend",
                },
                "current": asdict(_load_config()),
            },
            ensure_ascii=False,
            indent=2,
        )
    return "Usage: /rtk [status|stats|reset-stats|config]"


def register(ctx) -> None:
    """Entry point called by the Hermes plugin system."""
    cfg = _load_config()
    if cfg.mode == "off":
        logger.info("[rtk] Hermes plugin disabled by RTK_HERMES_MODE=off")
        return

    register_command = getattr(ctx, "register_command", None)
    if callable(register_command):
        try:
            register_command("rtk", handler=_handle_command, description="RTK rewrite status and metrics")
        except Exception as exc:  # pragma: no cover - defensive compatibility path
            logger.debug("[rtk] slash command registration skipped: %s", exc)

    if not _check_rtk():
        logger.warning("[rtk] rtk binary not found in PATH — rewrite hook disabled")
        return

    ctx.register_hook("pre_tool_call", _pre_tool_call)
    logger.info("[rtk] Hermes plugin registered")
