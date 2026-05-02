# Security policy

## Supported versions

Security fixes target the latest released version of `rtk-hermes`.

## Reporting a vulnerability

Open a private security advisory on GitHub if available, or contact the maintainer through the repository owner profile.

Do not include secrets, tokens, private shell commands, customer data or full terminal history in public issues.

## Security model

`rtk-hermes` runs inside Hermes and intercepts terminal tool calls before execution. Its security posture is conservative:

- all command rewrite policy lives in RTK;
- the plugin passes the original command to `rtk rewrite` as a single subprocess argument;
- rewritten commands are applied only when RTK returns a different command with an allowed exit code;
- failures are fail-open, so the original command continues unchanged;
- metrics do not store raw command strings.

## Sensitive data guidance

When filing bugs, redact:

- API keys and tokens;
- passwords;
- private paths that expose customer names;
- SSH hosts and connection strings;
- proprietary command output.

Use `[REDACTED]` for anything sensitive.
