# Clean Android Agent Harness setup

> **Raw Prompt URL**: `https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.1.1/docs/setup-prompt.md`
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness`
> **Kit version**: `v1.1.1` — **SHA-256**: `b41ae46f92353973a2447a688b656e07a48afdc40e0235e065088771c8a037d3` (SHA-256 of every byte after this line; verify first — mismatch = STOP)

---
Before executing anything: verify that the SHA-256 of every byte after the **SHA-256** header line equals the header value. If it does not match, STOP and tell the developer the file was tampered with.

Perform a clean, local installation only after explicit developer approval:

1. Verify a Git checkout, root Gradle Wrapper, Python 3.10+, and a pinned v1 kit.
2. Select **Google Antigravity** (`antigravity`) as the primary AI host in setup.
3. Run the setup wizard through `python harness_cli.py init --repo <app> --kit <kit>`.
4. The installer configures `.agents/hooks.json` for hard mutation interception, provisions 7 specialist reviewer agents under `.agents/agents/<reviewer>/agent.md`, and sets the default Reviewer Call Safety Cap to 20.
5. Reviewer models inherit the lead agent model by omission without manual model or reasoning overrides.
6. Run `doctor --install-check` to verify the Antigravity installation. Report Antigravity as `HARD_ENFORCED`.

The installed AI workflow must analyze and plan without mutation, wait for explicit plan approval, then run only adaptive policy-selected skills, tests, Review Protocol V2 specialist reviewers, builds, and device checks.
