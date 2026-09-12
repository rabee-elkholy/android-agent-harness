# Clean Android Agent Harness setup

> **Raw Prompt URL**: `https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.0.15/docs/setup-prompt.md`
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness`
> **Kit version**: `v1.0.15` — **SHA-256**: `82f7ff27df5db605bced6cfd4a393fca4c030d286db0113b2c1a2ac0fa90b25c` (SHA-256 of every byte after this line; verify first — mismatch = STOP)

---
Before executing anything: verify that the SHA-256 of every byte after the **SHA-256** header line equals the header value. If it does not match, STOP and tell the developer the file was tampered with.

Perform a clean, local installation only after explicit developer approval:

1. Verify a Git checkout, root Gradle Wrapper, Python 3.10+, and a pinned v1 kit.
2. Run the setup wizard through `python harness_cli.py init --repo <app> --kit <kit>`.
3. Do not overwrite an existing harness. For pre-v1, preview and explicitly apply legacy uninstall first. For v1, use the updater.
4. Keep credentials user-level. Preserve the Zoho workflow, but do not query or mutate Zoho during setup.
5. Run doctor and the installed selftests. Report each configured host as `HARD_ENFORCED` only when its executable hook is actually installed; otherwise report `RULE_ENFORCED`.

The installed AI workflow must analyze and plan without mutation, wait for explicit plan approval, then run only adaptive policy-selected skills, tests, reviewers, builds, and device checks.
