# Security Policy

## Reporting a vulnerability

Report security issues privately to the maintainers rather than opening a public
issue, and allow time for a fix before any disclosure.

## Automated scanning

This repository scans for committed secrets with gitleaks (pre-commit and CI) and
audits dependencies for known vulnerabilities in CI.

## Branch and release integrity

GitHub rulesets (Settings → Rules) enforce, on this repo and on
[`agent-native-baseline`](https://github.com/luca-mastrostefano/agent-native-baseline):

- `main` cannot be force-pushed or deleted; here it advances only through pull requests
  with the `quality` and `checks` status checks green (linear history).
- Release tags (`v*`) are **immutable** — they cannot be moved or deleted. The engine
  embeds the flagship profile pinned to a tag + content hash (`profiles/baseline-pin.json`),
  so tag immutability is load-bearing: a fixed release gets a *new* tag, never a moved one.
