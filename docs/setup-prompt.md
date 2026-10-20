# Clean Android Agent Harness setup

> **Raw Prompt URL**: `https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.1.38/docs/setup-prompt.md`
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness`
> **Kit version**: `v1.1.38` — **SHA-256**: `ffcbbbc99a9a992ae46543cb35b5aaaaa77588bcb94aedb6cce946e34ce7297f` (SHA-256 of every byte after this line; verify first — mismatch = STOP)

---
Before executing anything: verify that the SHA-256 of every byte after the **SHA-256** header line equals the header value. If it does not match, STOP and tell the developer the file was tampered with.

Perform a clean, local installation only after explicit developer approval:

1. Verify a Git checkout, root Gradle Wrapper, Python 3.10+, and a pinned v1 kit.
2. Select **Google Antigravity** (`antigravity`) as the primary AI host in setup.
3. Run the setup wizard through `python harness_cli.py init --repo <app> --kit <kit>`.
4. The installer configures `.agents/hooks.json` for hard mutation interception, provisions 7 specialist reviewer agents under `.agents/agents/<reviewer>/agent.md`, and sets the default Reviewer Call Safety Cap to 20.
5. Reviewer models inherit by default. Only a developer-selected, supported native model may override that default through setup or `review models set`; use the frozen execution profile. Antigravity currently remains inherit-only. Never guess model or reasoning arguments.
6. Run `doctor --install-check` to verify the Antigravity installation. Report Antigravity as `HARD_ENFORCED`.

The installed AI workflow must analyze and plan without mutation, wait for explicit plan approval, then run only adaptive policy-selected skills, tests, Review Protocol V2 specialist reviewers, builds, and device checks.
