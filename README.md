# RTK Plugin for Hermes

[![GitHub release](https://img.shields.io/github/v/release/ogallotti/rtk-hermes)](https://github.com/ogallotti/rtk-hermes/releases)
[![CI](https://github.com/ogallotti/rtk-hermes/actions/workflows/ci.yml/badge.svg)](https://github.com/ogallotti/rtk-hermes/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/rtk-hermes)](https://pypi.org/project/rtk-hermes/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

`rtk-hermes` is a small Hermes Agent plugin that rewrites terminal commands through [RTK](https://github.com/rtk-ai/rtk) before execution.

Instead of letting Hermes run verbose shell commands directly, the plugin asks `rtk rewrite` for a lower-context equivalent:

```text
Hermes wants to run:  git status
Plugin rewrites to:   : RTK && rtk git status
Hermes executes:      rtk git status
```

RTK then returns filtered output to the LLM, which usually means fewer tokens in the context window.

## Status

- Hermes plugin entry point: `rtk-rewrite = "rtk_hermes"`
- Hermes hook used: `pre_tool_call`
- Default mode: rewrite terminal commands in place
- Failure mode: fail open; original command runs unchanged
- Current PyPI/GitHub release: `v1.2.3`
- PyPI publishing: automated through GitHub Actions Trusted Publishing; no long-lived PyPI token is required.

## Installation

### 1. Install RTK

```bash
brew install rtk
```

Alternative installer:

```bash
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh
```

Verify:

```bash
rtk --version
rtk rewrite "git status"
```

### 2. Install the plugin into Hermes' Python environment

Install into the same Python environment that runs `hermes`. Installing into system Python, conda, or a random virtualenv will not make the plugin visible to Hermes.

For the standard Hermes source install, use the bundled virtualenv directly:

```bash
HERMES_PY="$HOME/.hermes/hermes-agent/venv/bin/python"
"$HERMES_PY" -m pip install --upgrade rtk-hermes
```

If `hermes` is installed through a symlinked shim and the standard path does not exist, derive the Python executable from the real `hermes` path:

```bash
HERMES_BIN="$(command -v hermes)"
HERMES_REAL="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$HERMES_BIN")"
HERMES_PY="$(dirname "$HERMES_REAL")/python"
"$HERMES_PY" -m pip install --upgrade rtk-hermes
```

If that fails with `No module named pip`, the Hermes virtualenv exists but was created without pip. Use `uv` to install into that virtualenv without touching system Python:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
~/.local/bin/uv pip install --python "$HOME/.hermes/hermes-agent/venv/bin/python" --upgrade rtk-hermes
```

On Debian/Ubuntu, if you see `This environment is externally managed`, you are using system `pip`, not Hermes' virtualenv. Do not use `--break-system-packages`; point the install at Hermes' Python or use the `uv pip install --python ...` command above.

Pinned GitHub release wheel, if you need it:

```bash
HERMES_PY="$HOME/.hermes/hermes-agent/venv/bin/python"
"$HERMES_PY" -m pip install \
  "https://github.com/ogallotti/rtk-hermes/releases/download/v1.2.3/rtk_hermes-1.2.3-py3-none-any.whl"
```

### 3. Enable the plugin in Hermes

Hermes v0.11+ treats pip-distributed plugins as opt-in. Add `rtk-rewrite` to `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - rtk-rewrite
```

Restart Hermes or start a new session after changing plugin config.

Current Hermes CLI caveat: `hermes plugins enable rtk-rewrite` may not recognize pip-only entry points even when the plugin is installed correctly. Editing `plugins.enabled` directly is the reliable path.

## How it works

```text
Agent calls terminal(command="cargo test --nocapture")
  -> rtk-hermes receives Hermes' pre_tool_call hook
  -> plugin calls: rtk rewrite "cargo test --nocapture"
  -> RTK returns: rtk cargo test --nocapture
  -> plugin mutates args["command"] in place
  -> Hermes executes the rewritten command
  -> RTK-filtered output reaches the model
```

The plugin does not implement command rules itself. All rewrite logic lives in RTK, so new RTK rules become available without a plugin release.

## What gets rewritten

Anything supported by `rtk rewrite`, including common commands around:

- Git status, logs and diffs
- `ls`, `find`, `grep` and file inspection
- test runners such as `pytest` and `cargo test`
- package managers and build tools
- Docker and Kubernetes commands

Check RTK's own docs for the current command list: https://github.com/rtk-ai/rtk#commands

## Runtime configuration

`rtk-hermes` intentionally avoids adding extra Hermes tools or MCP servers. Runtime behavior is controlled through environment variables so the plugin stays lightweight.

| Variable | Default | Values | Behavior |
|---|---:|---|---|
| `RTK_HERMES_MODE` | `rewrite` | `rewrite`, `suggest`, `off` | `rewrite` mutates terminal commands; `suggest` logs suggestions without changing execution; `off` disables the plugin at register time. |
| `RTK_HERMES_TIMEOUT_MS` | `2000` | positive integer | Max time spent in `rtk rewrite` per command. |
| `RTK_HERMES_PREVIEW_MARKER` | `true` | `true`, `false` | Prefixes rewritten shell commands with `: RTK &&` so Hermes previews clearly show RTK is active. |
| `RTK_HERMES_BACKENDS` | `local` | comma-separated backend names, or `all` | Terminal backends where rewrites are allowed. Defaults to local only because SSH, Docker and remote sandboxes also need `rtk` installed inside the execution backend. |

Example:

```bash
export RTK_HERMES_MODE=suggest
export RTK_HERMES_TIMEOUT_MS=500
export RTK_HERMES_PREVIEW_MARKER=false
export RTK_HERMES_BACKENDS=local
hermes
```

For SSH or another remote backend, only opt in if `rtk` is installed in that execution environment too:

```bash
export RTK_HERMES_BACKENDS=local,ssh
# or, if every configured backend has rtk available:
export RTK_HERMES_BACKENDS=all
```

## Slash command

When the running Hermes version supports plugin slash commands, the plugin registers:

```text
/rtk status
/rtk stats
/rtk reset-stats
/rtk config
```

The command returns JSON so it is easy to inspect or paste into an issue.

The metrics are process-local counters only. Commands are never stored in metrics to avoid leaking secrets or private shell input.

## RTK rewrite exit codes

`rtk rewrite` uses exit codes to describe its decision:

| Code | Meaning | Plugin behavior |
|---:|---|---|
| `0` | Rewrite allowed | Apply rewrite when stdout contains a different command. |
| `1` | No equivalent | Pass through the original command. |
| `2` | Deny rule matched | Pass through the original command. |
| `3` | Ask/confirm verdict; rewritten command exists on stdout | Apply rewrite when stdout contains a different command. |

Exit code `3` is common for valid rewrites such as `git status -> rtk git status` and `cat file -> rtk read file`, so the plugin treats both `0` and `3` as successful rewrites.

## Graceful degradation

The plugin should never block command execution.

| Condition | Behavior |
|---|---|
| RTK binary not found | Plugin does not register the rewrite hook. |
| Terminal backend is not enabled by `RTK_HERMES_BACKENDS` | Original command runs unchanged. |
| `rtk rewrite` times out | Original command runs unchanged. |
| `rtk rewrite` crashes | Original command runs unchanged. |
| No RTK equivalent | Original command runs unchanged. |
| Unexpected RTK exit code | Warning is logged; original command runs unchanged. |

## MCP and context mode

This plugin is not an MCP server and does not need to be one.

MCP exposes additional tools to Hermes. RTK rewriting needs to intercept Hermes' existing `terminal` tool before it executes. That belongs in the `pre_tool_call` plugin hook, not in MCP.

A pure `pre_tool_call` rewrite hook also avoids changing the tool schema sent to the model. That is safer for prompt caching than adding or removing tools mid-session.

## Why output compaction is not enabled here

Hermes also has hooks such as `transform_terminal_output` and `transform_tool_result`. They can compact output after tools run, but they are riskier because they can hide debugging evidence or alter structured tool results.

`rtk-hermes` stays conservative by default:

- rewrite before execution;
- let RTK filter command output;
- do not mutate `read_file`, `search_files`, `process`, or other non-terminal tool results.

If output compaction is added later, it should be opt-in and heavily tested.

## Verification

Check the installed entry point:

```bash
HERMES_PY="$HOME/.hermes/hermes-agent/venv/bin/python"
"$HERMES_PY" - <<'PY'
import importlib.metadata as md
for ep in md.entry_points().select(group="hermes_agent.plugins"):
    if ep.name == "rtk-rewrite":
        module = ep.load()
        print(ep.name, ep.value, ep.dist.metadata["Version"], hasattr(module, "register"))
PY
```

Expected shape:

```text
rtk-rewrite rtk_hermes 1.2.3 True
```

Check Hermes config:

```bash
python - <<'PY'
from pathlib import Path
import yaml
cfg = yaml.safe_load((Path.home() / ".hermes/config.yaml").read_text()) or {}
print(cfg.get("plugins", {}).get("enabled", []))
PY
```

Check RTK behavior:

```bash
python - <<'PY'
import subprocess
for cmd in ["ls -la", "git status", "cat /etc/hosts", "echo hello"]:
    cp = subprocess.run(["rtk", "rewrite", cmd], capture_output=True, text=True)
    print(cmd, "rc=", cp.returncode, "stdout=", cp.stdout.strip())
PY
```

Run tests from this repository:

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m build
```

## Troubleshooting

### Plugin installed but Hermes does not load it

Most likely cause: it was installed into the wrong Python environment.

Use the same interpreter chosen during installation:

```bash
HERMES_PY="$HOME/.hermes/hermes-agent/venv/bin/python"
"$HERMES_PY" -m pip show rtk-hermes
```

If that command cannot find the package, reinstall using the same interpreter or the `uv pip install --python ...` fallback from the installation section.

### `hermes plugins enable rtk-rewrite` says the plugin is not installed

This is a current Hermes CLI limitation for pip-only entry points. Edit `~/.hermes/config.yaml` directly:

```yaml
plugins:
  enabled:
    - rtk-rewrite
```

### Hermes shows `no register() function`

The installed package is old. Versions before `1.1.0` used the wrong entry point target.

Upgrade from PyPI:

```bash
HERMES_PY="$HOME/.hermes/hermes-agent/venv/bin/python"
"$HERMES_PY" -m pip install --upgrade rtk-hermes
```

If that Python has no pip, use:

```bash
~/.local/bin/uv pip install --python "$HOME/.hermes/hermes-agent/venv/bin/python" --upgrade rtk-hermes
```

Pinned GitHub release wheel:

```bash
HERMES_PY="$HOME/.hermes/hermes-agent/venv/bin/python"
"$HERMES_PY" -m pip install --force-reinstall \
  "https://github.com/ogallotti/rtk-hermes/releases/download/v1.2.3/rtk_hermes-1.2.3-py3-none-any.whl"
```

### Rewritten commands do not appear

Check:

1. `rtk --version` works in the same environment that starts Hermes.
2. `rtk rewrite "git status"` returns a rewritten command.
3. `plugins.enabled` contains `rtk-rewrite`.
4. Hermes was restarted after the config change.
5. `RTK_HERMES_MODE` is not set to `off` or `suggest`.
6. `RTK_HERMES_BACKENDS` includes the active terminal backend. By default, only `local` is enabled.

## Development

```bash
git clone https://github.com/ogallotti/rtk-hermes.git
cd rtk-hermes
python -m pip install -e '.[dev]'
python -m pytest
python -m build
```

Before releasing:

```bash
rm -rf dist/ build/ src/*.egg-info
python -m pytest
python -m build
python -m twine check dist/*
```

## License

MIT.
