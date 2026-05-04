"""Tests for rtk-hermes plugin."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 test envs
    import tomli as tomllib

import pytest

import rtk_hermes


ROOT = Path(__file__).resolve().parents[1]


def test_package_metadata_matches_module():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == rtk_hermes.__version__
    assert (
        pyproject["project"]["entry-points"]["hermes_agent.plugins"]["rtk-rewrite"]
        == "rtk_hermes"
    )


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    rtk_hermes._rtk_available = None
    rtk_hermes._reset_metrics()
    monkeypatch.delenv("RTK_HERMES_MODE", raising=False)
    monkeypatch.delenv("RTK_HERMES_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("RTK_HERMES_PREVIEW_MARKER", raising=False)
    monkeypatch.delenv("RTK_HERMES_BACKENDS", raising=False)
    monkeypatch.delenv("TERMINAL_ENV", raising=False)
    monkeypatch.delenv("TERMINAL_BACKEND", raising=False)
    yield
    rtk_hermes._rtk_available = None
    rtk_hermes._reset_metrics()


class TestConfig:
    def test_defaults(self):
        cfg = rtk_hermes._load_config()
        assert cfg.mode == "rewrite"
        assert cfg.timeout_ms == 2000
        assert cfg.preview_marker is True
        assert cfg.enabled_backends == ("local",)

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("RTK_HERMES_MODE", "suggest")
        monkeypatch.setenv("RTK_HERMES_TIMEOUT_MS", "500")
        monkeypatch.setenv("RTK_HERMES_PREVIEW_MARKER", "false")
        monkeypatch.setenv("RTK_HERMES_BACKENDS", "local,ssh")
        cfg = rtk_hermes._load_config()
        assert cfg.mode == "suggest"
        assert cfg.timeout_ms == 500
        assert cfg.preview_marker is False
        assert cfg.enabled_backends == ("local", "ssh")

    def test_backends_all(self, monkeypatch):
        monkeypatch.setenv("RTK_HERMES_BACKENDS", "all,ssh")
        cfg = rtk_hermes._load_config()
        assert cfg.enabled_backends == ("all",)

    def test_invalid_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("RTK_HERMES_MODE", "bad")
        monkeypatch.setenv("RTK_HERMES_TIMEOUT_MS", "bad")
        monkeypatch.setenv("RTK_HERMES_PREVIEW_MARKER", "bad")
        cfg = rtk_hermes._load_config()
        assert cfg.mode == "rewrite"
        assert cfg.timeout_ms == 2000
        assert cfg.preview_marker is True


class TestBackendSelection:
    def test_default_backend_is_local(self):
        assert rtk_hermes._current_terminal_backend({}) == "local"

    def test_terminal_env_backend(self, monkeypatch):
        monkeypatch.setenv("TERMINAL_ENV", "ssh")
        assert rtk_hermes._current_terminal_backend({}) == "ssh"

    def test_args_backend_wins(self, monkeypatch):
        monkeypatch.setenv("TERMINAL_ENV", "local")
        assert rtk_hermes._current_terminal_backend({"env_type": "docker"}) == "docker"

    def test_backend_enabled(self):
        assert rtk_hermes._backend_enabled("local", rtk_hermes.RtkHermesConfig()) is True
        assert rtk_hermes._backend_enabled("ssh", rtk_hermes.RtkHermesConfig()) is False
        assert rtk_hermes._backend_enabled("ssh", rtk_hermes.RtkHermesConfig(enabled_backends=("all",))) is True


class TestCheckRtk:
    def test_found(self):
        with patch("shutil.which", return_value="/usr/local/bin/rtk"):
            assert rtk_hermes._check_rtk() is True

    def test_not_found(self):
        with patch("shutil.which", return_value=None):
            assert rtk_hermes._check_rtk() is False
        assert rtk_hermes._metrics.missing_rtk == 1

    def test_cached(self):
        with patch("shutil.which", return_value="/usr/local/bin/rtk") as m:
            rtk_hermes._check_rtk()
            rtk_hermes._check_rtk()
            m.assert_called_once()

    def test_refresh_rechecks(self):
        with patch("shutil.which", side_effect=[None, "/usr/local/bin/rtk"]) as m:
            assert rtk_hermes._check_rtk() is False
            assert rtk_hermes._check_rtk(refresh=True) is True
            assert m.call_count == 2


class TestPreviewMarker:
    def test_marker_enabled(self):
        assert rtk_hermes._with_preview_marker("rtk git status", enabled=True) == ": RTK && rtk git status"

    def test_marker_disabled(self):
        assert rtk_hermes._with_preview_marker("rtk git status", enabled=False) == "rtk git status"

    def test_marker_idempotent(self):
        assert rtk_hermes._with_preview_marker(": RTK && rtk git status", enabled=True) == ": RTK && rtk git status"


class TestTryRewrite:
    def _fake(self, stdout="", rc=0, stderr=""):
        return subprocess.CompletedProcess([], rc, stdout=stdout, stderr=stderr)

    def test_rewrites_on_exit_0(self):
        with patch("subprocess.run", return_value=self._fake("rtk git status\n", rc=0)):
            assert rtk_hermes._try_rewrite("git status") == "rtk git status"
        assert rtk_hermes._metrics.rewritten == 0

    def test_rewrites_on_exit_3(self):
        with patch("subprocess.run", return_value=self._fake("rtk git status\n", rc=3)):
            assert rtk_hermes._try_rewrite("git status") == "rtk git status"
        assert rtk_hermes._metrics.rewritten == 0

    def test_same_command_returns_none(self):
        with patch("subprocess.run", return_value=self._fake("echo hello\n")):
            assert rtk_hermes._try_rewrite("echo hello") is None
        assert rtk_hermes._metrics.same_command == 1

    def test_exit_1_returns_none(self):
        with patch("subprocess.run", return_value=self._fake("", rc=1)):
            assert rtk_hermes._try_rewrite("custom_cmd") is None
        assert rtk_hermes._metrics.no_equivalent == 1

    def test_exit_2_returns_none(self):
        with patch("subprocess.run", return_value=self._fake("", rc=2)):
            assert rtk_hermes._try_rewrite("rm -rf /") is None
        assert rtk_hermes._metrics.denied == 1

    def test_empty_stdout_returns_none(self):
        with patch("subprocess.run", return_value=self._fake("")):
            assert rtk_hermes._try_rewrite("git status") is None

    def test_unexpected_exit_code_logs_warning_without_raw_stderr(self, caplog):
        stderr = "boom token=SECRET123 command='deploy prod'"
        with patch("subprocess.run", return_value=self._fake("", rc=99, stderr=stderr)):
            with caplog.at_level("WARNING", logger="rtk_hermes"):
                assert rtk_hermes._try_rewrite("git status") is None
        assert "unexpected `rtk rewrite` exit code 99" in caplog.text
        assert "stderr redacted" in caplog.text
        assert "SECRET123" not in caplog.text
        assert "deploy prod" not in caplog.text
        assert "git status" not in caplog.text
        assert rtk_hermes._metrics.unexpected_exit_codes == 1

    def test_timeout_returns_none(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("rtk", 2)):
            assert rtk_hermes._try_rewrite("git status") is None
        assert rtk_hermes._metrics.timeouts == 1

    def test_file_not_found_returns_none(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert rtk_hermes._try_rewrite("git status") is None
        assert rtk_hermes._metrics.errors == 1

    def test_os_error_returns_none(self):
        with patch("subprocess.run", side_effect=OSError("broken")):
            assert rtk_hermes._try_rewrite("git status") is None
        assert rtk_hermes._metrics.errors == 1

    def test_strips_whitespace(self):
        with patch("subprocess.run", return_value=self._fake("  rtk ls  \n")):
            assert rtk_hermes._try_rewrite("ls") == "rtk ls"

    def test_passes_command_as_arg_and_timeout(self):
        cfg = rtk_hermes.RtkHermesConfig(timeout_ms=500)
        with patch("subprocess.run", return_value=self._fake("", rc=1)) as m:
            rtk_hermes._try_rewrite("git log --oneline -5", config=cfg)
            m.assert_called_once_with(
                ["rtk", "rewrite", "git log --oneline -5"],
                capture_output=True,
                text=True,
                timeout=0.5,
            )


class TestPreToolCall:
    def test_rewrites_terminal_with_preview_marker(self):
        args = {"command": "git status"}
        with patch.object(rtk_hermes, "_try_rewrite", return_value="rtk git status"):
            rtk_hermes._pre_tool_call(tool_name="terminal", args=args, task_id="t")
        assert args["command"] == ": RTK && rtk git status"
        assert rtk_hermes._metrics.rewritten == 1

    def test_can_disable_preview_marker(self, monkeypatch):
        monkeypatch.setenv("RTK_HERMES_PREVIEW_MARKER", "false")
        args = {"command": "git status"}
        with patch.object(rtk_hermes, "_try_rewrite", return_value="rtk git status"):
            rtk_hermes._pre_tool_call(tool_name="terminal", args=args, task_id="t")
        assert args["command"] == "rtk git status"

    def test_suggest_mode_does_not_mutate_command(self, monkeypatch):
        monkeypatch.setenv("RTK_HERMES_MODE", "suggest")
        args = {"command": "git status"}
        with patch.object(rtk_hermes, "_try_rewrite", return_value="rtk git status"):
            rtk_hermes._pre_tool_call(tool_name="terminal", args=args, task_id="t")
        assert args["command"] == "git status"
        assert rtk_hermes._metrics.suggested == 1

    def test_off_mode_skips_rewrite(self, monkeypatch):
        monkeypatch.setenv("RTK_HERMES_MODE", "off")
        args = {"command": "git status"}
        with patch.object(rtk_hermes, "_try_rewrite") as m:
            rtk_hermes._pre_tool_call(tool_name="terminal", args=args, task_id="t")
            m.assert_not_called()
        assert args["command"] == "git status"

    def test_ssh_backend_skips_by_default(self, monkeypatch):
        monkeypatch.setenv("TERMINAL_ENV", "ssh")
        args = {"command": "git status"}
        with patch.object(rtk_hermes, "_try_rewrite") as m:
            rtk_hermes._pre_tool_call(tool_name="terminal", args=args, task_id="t")
            m.assert_not_called()
        assert args["command"] == "git status"
        assert rtk_hermes._metrics.skipped_backend == 1

    def test_ssh_backend_can_be_enabled(self, monkeypatch):
        monkeypatch.setenv("TERMINAL_ENV", "ssh")
        monkeypatch.setenv("RTK_HERMES_BACKENDS", "local,ssh")
        args = {"command": "git status"}
        with patch.object(rtk_hermes, "_try_rewrite", return_value="rtk git status"):
            rtk_hermes._pre_tool_call(tool_name="terminal", args=args, task_id="t")
        assert args["command"] == ": RTK && rtk git status"

    def test_backend_arg_skips_when_not_enabled(self):
        args = {"command": "git status", "env_type": "docker"}
        with patch.object(rtk_hermes, "_try_rewrite") as m:
            rtk_hermes._pre_tool_call(tool_name="terminal", args=args, task_id="t")
            m.assert_not_called()
        assert args["command"] == "git status"

    def test_ignores_already_rtk_command(self):
        args = {"command": "rtk git status"}
        with patch.object(rtk_hermes, "_try_rewrite") as m:
            rtk_hermes._pre_tool_call(tool_name="terminal", args=args, task_id="t")
            m.assert_not_called()

    def test_ignores_marked_command(self):
        args = {"command": ": RTK && rtk git status"}
        with patch.object(rtk_hermes, "_try_rewrite") as m:
            rtk_hermes._pre_tool_call(tool_name="terminal", args=args, task_id="t")
            m.assert_not_called()

    def test_ignores_non_terminal(self):
        args = {"command": "git status"}
        with patch.object(rtk_hermes, "_try_rewrite") as m:
            rtk_hermes._pre_tool_call(tool_name="web_search", args=args, task_id="t")
            m.assert_not_called()

    def test_ignores_missing_command(self):
        with patch.object(rtk_hermes, "_try_rewrite") as m:
            rtk_hermes._pre_tool_call(tool_name="terminal", args={}, task_id="t")
            m.assert_not_called()

    def test_ignores_empty_command(self):
        with patch.object(rtk_hermes, "_try_rewrite") as m:
            rtk_hermes._pre_tool_call(tool_name="terminal", args={"command": ""}, task_id="t")
            m.assert_not_called()

    def test_ignores_non_string_command(self):
        with patch.object(rtk_hermes, "_try_rewrite") as m:
            rtk_hermes._pre_tool_call(tool_name="terminal", args={"command": 123}, task_id="t")
            m.assert_not_called()

    def test_no_mutation_when_none(self):
        args = {"command": "echo hi"}
        with patch.object(rtk_hermes, "_try_rewrite", return_value=None):
            rtk_hermes._pre_tool_call(tool_name="terminal", args=args, task_id="t")
        assert args["command"] == "echo hi"

    def test_preserves_other_args(self):
        args = {"command": "git status", "timeout": 30, "workdir": "/tmp"}
        with patch.object(rtk_hermes, "_try_rewrite", return_value="rtk git status"):
            rtk_hermes._pre_tool_call(tool_name="terminal", args=args, task_id="t")
        assert args == {"command": ": RTK && rtk git status", "timeout": 30, "workdir": "/tmp"}

    def test_handles_extra_kwargs(self):
        args = {"command": "git status"}
        with patch.object(rtk_hermes, "_try_rewrite", return_value="rtk git status"):
            rtk_hermes._pre_tool_call(tool_name="terminal", args=args, task_id="t", extra="x")
        assert args["command"] == ": RTK && rtk git status"


class TestSlashCommand:
    def test_status_returns_json(self):
        with patch.object(rtk_hermes, "_check_rtk", return_value=True):
            data = rtk_hermes.json.loads(rtk_hermes._handle_command("status"))
        assert data["version"] == rtk_hermes.__version__
        assert data["rtk_available"] is True
        assert data["config"]["mode"] == "rewrite"
        assert "metrics" in data

    def test_stats_returns_json(self):
        data = rtk_hermes.json.loads(rtk_hermes._handle_command("stats"))
        assert data["attempted"] == 0

    def test_reset_stats(self):
        rtk_hermes._metrics.attempted = 3
        assert rtk_hermes._handle_command("reset-stats") == "RTK Hermes metrics reset."
        assert rtk_hermes._metrics.attempted == 0

    def test_config_returns_json(self):
        data = rtk_hermes.json.loads(rtk_hermes._handle_command("config"))
        assert "RTK_HERMES_MODE" in data["env"]
        assert "RTK_HERMES_BACKENDS" in data["env"]
        assert data["current"]["enabled_backends"] == ["local"]

    def test_help_for_unknown(self):
        assert "Usage: /rtk" in rtk_hermes._handle_command("unknown")


class TestRegister:
    def test_registers_when_available(self):
        ctx = MagicMock()
        with patch.object(rtk_hermes, "_check_rtk", return_value=True):
            rtk_hermes.register(ctx)
        ctx.register_hook.assert_called_once_with("pre_tool_call", rtk_hermes._pre_tool_call)
        ctx.register_command.assert_called_once()

    def test_registers_without_command_support(self):
        class FakeCtx:
            def __init__(self):
                self.hooks = []

            def register_hook(self, name, callback):
                self.hooks.append((name, callback))

        ctx = FakeCtx()
        with patch.object(rtk_hermes, "_check_rtk", return_value=True):
            rtk_hermes.register(ctx)
        assert ctx.hooks == [("pre_tool_call", rtk_hermes._pre_tool_call)]

    def test_skips_hook_when_rtk_missing_but_keeps_status_command(self):
        ctx = MagicMock()
        with patch.object(rtk_hermes, "_check_rtk", return_value=False):
            rtk_hermes.register(ctx)
        ctx.register_hook.assert_not_called()
        ctx.register_command.assert_called_once()

    def test_register_command_failure_does_not_block_hook(self):
        ctx = MagicMock()
        ctx.register_command.side_effect = TypeError("old Hermes signature")
        with patch.object(rtk_hermes, "_check_rtk", return_value=True):
            rtk_hermes.register(ctx)
        ctx.register_hook.assert_called_once_with("pre_tool_call", rtk_hermes._pre_tool_call)

    def test_skips_when_mode_off(self, monkeypatch):
        monkeypatch.setenv("RTK_HERMES_MODE", "off")
        ctx = MagicMock()
        with patch.object(rtk_hermes, "_check_rtk") as m:
            rtk_hermes.register(ctx)
            m.assert_not_called()
        ctx.register_hook.assert_not_called()

    def test_no_crash_when_missing(self):
        ctx = MagicMock()
        with patch.object(rtk_hermes, "_check_rtk", return_value=False):
            rtk_hermes.register(ctx)


class TestIntegration:
    def test_full_flow(self):
        hooks = {}

        class FakeCtx:
            def register_hook(self, name, cb):
                hooks[name] = cb

            def register_command(self, *_args, **_kwargs):
                pass

        with patch.object(rtk_hermes, "_check_rtk", return_value=True):
            rtk_hermes.register(FakeCtx())

        args = {"command": "cargo test"}
        fake = subprocess.CompletedProcess([], 3, stdout="rtk cargo test\n", stderr="")
        with patch("subprocess.run", return_value=fake):
            hooks["pre_tool_call"](tool_name="terminal", args=args, task_id="t")
        assert args["command"] == ": RTK && rtk cargo test"

    def test_full_flow_no_rewrite(self):
        hooks = {}

        class FakeCtx:
            def register_hook(self, name, cb):
                hooks[name] = cb

            def register_command(self, *_args, **_kwargs):
                pass

        with patch.object(rtk_hermes, "_check_rtk", return_value=True):
            rtk_hermes.register(FakeCtx())

        args = {"command": "echo hello"}
        fake = subprocess.CompletedProcess([], 1, stdout="", stderr="")
        with patch("subprocess.run", return_value=fake):
            hooks["pre_tool_call"](tool_name="terminal", args=args, task_id="t")
        assert args["command"] == "echo hello"

    def test_full_flow_crash(self):
        hooks = {}

        class FakeCtx:
            def register_hook(self, name, cb):
                hooks[name] = cb

            def register_command(self, *_args, **_kwargs):
                pass

        with patch.object(rtk_hermes, "_check_rtk", return_value=True):
            rtk_hermes.register(FakeCtx())

        args = {"command": "git status"}
        with patch("subprocess.run", side_effect=OSError("segfault")):
            hooks["pre_tool_call"](tool_name="terminal", args=args, task_id="t")
        assert args["command"] == "git status"
