# RTK Plugin for Hermes

[![PyPI](https://img.shields.io/pypi/v/rtk-hermes)](https://pypi.org/project/rtk-hermes/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Transparently rewrites shell commands executed via [Hermes](https://github.com/NousResearch/hermes-agent)'s `terminal` tool to their [RTK](https://github.com/rtk-ai/rtk) equivalents, achieving **60-90% LLM token savings**.

## Installation

```bash
# 1. Install RTK
brew install rtk
# or: curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh

# 2. Install the plugin
~/.hermes/hermes-agent/venv/bin/python -m pip install rtk-hermes

# 3. Restart Hermes — the plugin auto-registers, no config needed
```

## How it works

```
Agent runs: terminal(command="cargo test --nocapture")
  → Plugin intercepts pre_tool_call hook
  → Calls `rtk rewrite "cargo test --nocapture"`
  → Mutates args["command"] = "rtk cargo test --nocapture"
  → Agent executes the rewritten command
  → Filtered output reaches LLM (~90% fewer tokens)
```

The plugin registers a `pre_tool_call` hook that intercepts `terminal` tool calls. When the agent runs a command like `git status`, the plugin delegates to `rtk rewrite` which returns the optimized command (e.g. `rtk git status`). The compressed output enters the agent's context window, saving tokens.

All rewrite logic lives in RTK itself (`rtk rewrite`). This plugin is a **thin delegate** — when new filters are added to RTK, the plugin picks them up automatically with zero changes.

## What gets rewritten

Everything that `rtk rewrite` supports (30+ commands): git, grep, find, ls, cargo, pytest, npm, docker, kubectl, and more. See the [full command list](https://github.com/rtk-ai/rtk#commands).

## Measured savings

| Command | Token savings |
|---------|--------------|
| `cargo test` | 90-99% |
| `git log --stat` | 87% |
| `ls -la` | 78% |
| `git status` | 66% |
| `grep` (single file) | 52% |

## Configuration

The plugin is enabled by default when RTK is found in `$PATH`. To disable:

```yaml
# ~/.hermes/config.yaml
plugins:
  disabled:
    - rtk-rewrite
```

## Graceful degradation

The plugin **never blocks command execution**:

- RTK binary not found → plugin disabled silently
- `rtk rewrite` times out (>2s) → command passes through unchanged
- `rtk rewrite` crashes → command passes through unchanged
- No RTK equivalent → command passes through unchanged

## License

MIT — same as RTK.
