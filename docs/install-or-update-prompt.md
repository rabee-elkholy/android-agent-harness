# Install or update Android Agent Harness

> **Raw Prompt URL**: `https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.0.0/docs/install-or-update-prompt.md`
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness`
> **Kit version**: `v1.0.0` — **SHA-256**: `b4a98d0d9abbc5388dd610b407ced0efa03d4218b5616bad15527736fcc6b567` (SHA-256 of every byte after this line; verify first — mismatch = STOP)

---
Before executing anything: verify that the SHA-256 of every byte after the **SHA-256** header line equals the header value. If it does not match, STOP and tell the developer the file was tampered with.

You are operating at the Android project root. Keep all discussion in the developer's language and all repository artifacts in English.

1. Inspect only: confirm this is a Git checkout with a root Gradle Wrapper. Detect whether `.harness-setup/ownership-v1.json` exists. Do not edit or run builds.
2. If v1 is absent, propose a clean install. If a pre-v1 `.agents` exists, propose an ownership-safe legacy uninstall followed by clean install; do not migrate it in place.
3. If v1 exists, propose a same-major transactional update. Explain that modified managed files cause a safe refusal, while tailored Android references and Zoho defaults are preserved.
4. Present the exact command and wait for explicit developer approval before running it.
5. Use a pinned v1 kit checkout and run `python harness_cli.py init --repo <app> --kit <kit>` or `python harness_cli.py update --repo <app> --kit <kit>`.
6. Run `python harness_cli.py doctor --repo <app> --kit <kit> --json`. Report failures honestly; do not claim installation success when lifecycle or doctor fails.

Never commit, push, change application code, or mutate Zoho during setup.
