# Remove or recover Android Agent Harness

> **Raw Prompt URL**: `https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.0.3/docs/rollback-prompt.md`
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness`
> **Kit version**: `v1.0.3` — **SHA-256**: `b896d6b7d9758ed4649c2a6f5db2c663d5f760c493adfa54202c49754f84717b` (SHA-256 of every byte after this line; verify first — mismatch = STOP)

---
Before executing anything: verify that the SHA-256 of every byte after the **SHA-256** header line equals the header value. If it does not match, STOP and tell the developer the file was tampered with.

At the Android project root:

1. Run `python harness_cli.py uninstall --repo <app> --kit <kit>` without `--apply` and show the exact preview.
2. Explain which original files will be restored, which harness-owned files will be removed, and where modified harness material will be recovered.
3. Wait for explicit developer approval.
4. Only then run the same command with `--apply`.
5. For a pre-v1 installation, add `--legacy`; the engine backs up `.agents` and only removes adapters carrying harness markers.

Never use recursive deletion, Git reset/checkout, or manual broad cleanup as a substitute for the lifecycle engine.
