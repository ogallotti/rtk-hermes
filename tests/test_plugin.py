"""Tests for rtk-hermes plugin."""

import subprocess
import tomllib
from pathlib import Path
from unittest.mock import MagicMock, patch

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
def _reset_cache():
    rtk_hermes._rtk_available = None
    yield
    rtk_hermes._rtk_available = None


class TestCheckRtk:
    def test_found(self):
        with patch("shutil.which", return_value="/usr/local/bin/rtk"):
            assert rtk_hermes._check_rtk() is True

    def test_not_found(self):
        with patch("shutil.which", return_value=None):
            assert rtk_hermes._check_rtk() is False

    def test_cached(self):
        with patch("shutil.which", return_value="/usr/local/bin/rtk") as m:
            rtk_hermes._check_rtk()
            rtk_hermes._check_rtk()
            m.assert_called_once()


class TestTryRewrite:
    def _fake(self, stdout="", rc=0, stderr=""):
        return subprocess.CompletedProcess([], rc, stdout=stdout, stderr=stderr)

    def test_rewrites_on_exit_0(self):
        with patch("subprocess.run", return_value=self._fake("rtk git status\n", rc=0)):
            assert rtk_hermes._try_rewrite("git status") == "rtk git status"

    def test_rewrites_on_exit_3(self):
        with patch("subprocess.run", return_value=self._fake("rtk git status\n", rc=3)):
            assert rtk_hermes._try_rewrite("git status") == "rtk git status"

    def test_same_command_returns_none(self):
        with patch("subprocess.run", return_value=self._fake("echo hello\n")):
            assert rtk_hermes._try_rewrite("echo hello") is None

    def test_exit_1_returns_none(self):
        with patch("subprocess.run", return_value=self._fake("", rc=1)):
            assert rtk_hermes._try_rewrite("custom_cmd") is None

    def test_exit_2_returns_none(self):
        with patch("subprocess.run", return_value=self._fake("", rc=2)):
            assert rtk_hermes._try_rewrite("rm -rf /") is None

    def test_empty_stdout_returns_none(self):
        with patch("subprocess.run", return_value=self._fake("")):
            assert rtk_hermes._try_rewrite("git status") is None

    def test_unexpected_exit_code_logs_warning(self, caplog):
        with patch("subprocess.run", return_value=self._fake("", rc=99, stderr="boom")):
            with caplog.at_level("WARNING", logger="rtk_hermes"):
                assert rtk_hermes._try_rewrite("git status") is None
        assert "unexpected `rtk rewrite` exit code 99" in caplog.text

    def test_timeout_returns_none(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("rtk", 2)):
            assert rtk_hermes._try_rewrite("git status") is None

    def test_file_not_found_returns_none(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert rtk_hermes._try_rewrite("git status") is None

    def test_os_error_returns_none(self):
        with patch("subprocess.run", side_effect=OSError("broken")):
            assert rtk_hermes._try_rewrite("git status") is None

    def test_strips_whitespace(self):
        with patch("subprocess.run", return_value=self._fake("  rtk ls  \n")):
            assert rtk_hermes._try_rewrite("ls") == "rtk ls"

    def test_passes_command_as_arg(self):
        with patch("subprocess.run", return_value=self._fake("", rc=1)) as m:
            rtk_hermes._try_rewrite("git log --oneline -5")
            m.assert_called_once_with(
                ["rtk", "rewrite", "git log --oneline -5"],
                capture_output=True, text=True, timeout=2,
            )


class TestPreToolCall:
    def test_rewrites_terminal(self):
        args = {"command": "git status"}
        with patch.object(rtk_hermes, "_try_rewrite", return_value="rtk git status"):
            rtk_hermes._pre_tool_call(tool_name="terminal", args=args, task_id="t")
        assert args["command"] == "rtk git status"

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
        assert args == {"command": "rtk git status", "timeout": 30, "workdir": "/tmp"}

    def test_handles_extra_kwargs(self):
        args = {"command": "git status"}
        with patch.object(rtk_hermes, "_try_rewrite", return_value="rtk git status"):
            rtk_hermes._pre_tool_call(tool_name="terminal", args=args, task_id="t", extra="x")
        assert args["command"] == "rtk git status"


class TestRegister:
    def test_registers_when_available(self):
        ctx = MagicMock()
        with patch.object(rtk_hermes, "_check_rtk", return_value=True):
            rtk_hermes.register(ctx)
        ctx.register_hook.assert_called_once_with("pre_tool_call", rtk_hermes._pre_tool_call)

    def test_skips_when_missing(self):
        ctx = MagicMock()
        with patch.object(rtk_hermes, "_check_rtk", return_value=False):
            rtk_hermes.register(ctx)
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

        with patch.object(rtk_hermes, "_check_rtk", return_value=True):
            rtk_hermes.register(FakeCtx())

        args = {"command": "cargo test"}
        fake = subprocess.CompletedProcess([], 3, stdout="rtk cargo test\n", stderr="")
        with patch("subprocess.run", return_value=fake):
            hooks["pre_tool_call"](tool_name="terminal", args=args, task_id="t")
        assert args["command"] == "rtk cargo test"

    def test_full_flow_no_rewrite(self):
        hooks = {}

        class FakeCtx:
            def register_hook(self, name, cb):
                hooks[name] = cb

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

        with patch.object(rtk_hermes, "_check_rtk", return_value=True):
            rtk_hermes.register(FakeCtx())

        args = {"command": "git status"}
        with patch("subprocess.run", side_effect=OSError("segfault")):
            hooks["pre_tool_call"](tool_name="terminal", args=args, task_id="t")
        assert args["command"] == "git status"
