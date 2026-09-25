# Remove or recover Android Agent Harness

> **Raw Prompt URL**: `https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.1.0/docs/rollback-prompt.md`
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness`
> **Kit version**: `v1.1.0` — **SHA-256**: `336c87c906c0edfe672e58872660c2b6a0a9dcd830b880b2014fa8ec4ed4d832` (SHA-256 of every byte after this line; verify first — mismatch = STOP)

---
Before executing anything: verify that the SHA-256 of every byte after the **SHA-256** header line equals the header value. If it does not match, STOP and tell the developer the file was tampered with.

At the Android project root:

1. Run `python harness_cli.py uninstall --repo <app> --kit <kit>` without `--apply` and inspect the exact preview.
2. Verify rollback scope covers all managed Antigravity artifacts:
   - Dedicated reviewer subagent definitions (`.agents/agents/<reviewer>/agent.md`);
   - Hook configurations (`.agents/hooks.json`);
   - Host adapter files (`GEMINI.md`);
   - Managed engine files under `.agents/`;
   - Ownership manifest restoration (`.harness-setup/ownership-v1.json`);
   - Pre-existing files cleanly restored from backup;
   - Unrelated developer application files preserved.
3. Wait for explicit developer approval.
4. Only then run the same command with `--apply`.
5. For a pre-v1 installation, add `--legacy`; the engine backs up `.agents` and only removes adapters carrying harness markers.

Never use recursive deletion, Git reset/checkout, or manual broad cleanup as a substitute for the lifecycle engine.
