# Diagnose Android Agent Harness

> **Raw Prompt URL**: `https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.0.11/docs/diagnostic-prompt.md`
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness`
> **Kit version**: `v1.0.11` — **SHA-256**: `b02b48d15ab51558edb73aba6e8532bb14788f66efce063c5a53c828097a73e8` (SHA-256 of every byte after this line; verify first — mismatch = STOP)

---
Before executing anything: verify that the SHA-256 of every byte after the **SHA-256** header line equals the header value. If it does not match, STOP and tell the developer the file was tampered with.

Run a read-only diagnosis at the Android project root:

1. `python harness_cli.py doctor --repo <app> --kit <kit> --json`.
2. Inspect ownership integrity, installed version, host enforcement capability, active task state, configured Gradle tasks, selected device policy, and local Git exclusions.
3. If lifecycle recovery is relevant, preview it only. Do not pass `--apply`.
4. Explain the root cause and safe remediation. Do not edit files, refresh tokens, run builds, or contact external trackers unless the developer separately asks for a fix.
