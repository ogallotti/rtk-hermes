# Contributing

Thanks for improving `rtk-hermes`.

## Scope

`rtk-hermes` should stay a thin, reliable Hermes plugin. Command rewrite rules belong in RTK itself. This repository is responsible for:

- loading correctly as a Hermes pip plugin;
- installing cleanly into Hermes' Python environment;
- calling `rtk rewrite` safely;
- mutating Hermes terminal tool calls in place;
- failing open when RTK cannot rewrite;
- documenting Hermes compatibility quirks.

Avoid adding broad output compaction by default. Hooks such as `transform_terminal_output` and `transform_tool_result` can save tokens, but they can also hide debugging evidence or alter structured tool results. If added, they must be opt-in and covered by tests.

## Local setup

```bash
git clone https://github.com/ogallotti/rtk-hermes.git
cd rtk-hermes
python -m pip install -e '.[dev]'
python -m pytest
```

## Test matrix

The package supports Python 3.9 through 3.13. CI runs the test suite on all supported versions.

Before opening a PR, run:

```bash
python -m pytest
python -m build
python -m twine check dist/*
```

## Hermes compatibility checklist

Before changing plugin loading or registration, verify:

- pip entry point points to the module, not the function:

  ```toml
  [project.entry-points."hermes_agent.plugins"]
  rtk-rewrite = "rtk_hermes"
  ```

- the module exposes `register(ctx)`;
- the plugin is enabled in Hermes config:

  ```yaml
  plugins:
    enabled:
      - rtk-rewrite
  ```

- install instructions use Hermes' own Python interpreter and avoid system `pip`:

  ```bash
  HERMES_PY="$HOME/.hermes/hermes-agent/venv/bin/python"
  "$HERMES_PY" -m pip install ...
  # If the Hermes venv has no pip:
  uv pip install --python "$HERMES_PY" ...
  ```

## RTK rewrite exit codes

Handle these codes deliberately:

- `0`: rewrite allowed; apply stdout when it differs from the original command.
- `1`: no equivalent; pass through.
- `2`: deny rule; pass through.
- `3`: ask/confirm verdict, but stdout may contain a valid rewrite; apply it when present and different.

Unexpected codes should log a warning and pass through.

## Security rules

- Do not store raw shell commands in persistent config, metrics, files or issue templates.
- Do not log command strings at warning or error level unless needed for debugging. Debug logs are acceptable.
- Never introduce shell parsing around `rtk rewrite`; pass the original command as a single subprocess argument:

  ```python
  subprocess.run(["rtk", "rewrite", command], ...)
  ```

- Keep fail-open behavior. The plugin must not block normal terminal execution if RTK is missing, slow or broken.

## Release process

PyPI publishing is designed to use Trusted Publishing through GitHub Actions, not long-lived API tokens.

One-time PyPI project configuration:

- Project: `rtk-hermes`
- Platform: GitHub Actions
- Owner: `ogallotti`
- Repository: `rtk-hermes`
- Workflow filename: `publish.yml`
- Environment name: `pypi`

After that is configured, publish by creating a GitHub release or by running the `Publish to PyPI` workflow manually from GitHub Actions.

Manual local upload with `twine` should be reserved for emergencies only.

## Pull request notes

Good PRs include:

- a short explanation of the Hermes or RTK behavior being changed;
- tests for each new branch or failure mode;
- README/CHANGELOG updates when user behavior changes;
- verification output from `python -m pytest`.
