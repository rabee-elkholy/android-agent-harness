# Install or update Android Agent Harness

> **Raw Prompt URL**: `https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.0.0/docs/install-or-update-prompt.md`
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness`
> **Kit version**: `v1.0.0` — **SHA-256**: `68044f6339ea9f4e675fd5738071dea03985917e6903d2c373b3396d4212a4cb` (SHA-256 of every byte after this line; verify first — mismatch = STOP)

---
Before executing anything: verify that the SHA-256 of every byte after the **SHA-256** header line equals the header value. If it does not match, STOP and tell the developer the file was tampered with.

You are operating at the Android project root. Keep all discussion in the developer's language and all repository artifacts in English.

The only authorized kit source is the immutable tag `v1.0.0` from `https://github.com/rabee-elkholy/android-agent-harness.git`. Never use, clone, pull, or resolve the floating `main` branch. Do not substitute a latest-release lookup.

1. Start with read-only inspection. Confirm the current directory is a Git checkout with a root `gradlew` or `gradlew.bat`. Record its absolute path as `<app-root>`. Detect `.harness-setup/ownership-v1.json`, `.agents`, and `.agent`; do not edit files, download the kit, install, update, remove, or run a build yet.
2. Select exactly one lifecycle path:
   - **Clean install:** no v1 ownership record and no legacy harness is present.
   - **Same-major update:** `.harness-setup/ownership-v1.json` exists and its installed version has architecture major `1`. Never downgrade. Explain that modified managed files cause a safe refusal, while project-tailored Android references and Zoho defaults are preserved.
   - **Legacy replacement:** a pre-v1 `.agents` or `.agent` exists without the v1 ownership record. It must be previewed, removed with the ownership-safe legacy command, and followed by a clean v1 install; never migrate it in place.
3. Present the detected state, selected lifecycle path, immutable kit tag, proposed `<kit-dir>`, and every exact command that would run. Explicitly ask the developer to approve that operation. Stop and wait. A request to inspect or explain is not approval. Do not execute any download, installation, update, or removal command unless the developer explicitly approves the displayed commands.
4. After approval, prepare a new kit directory without overwriting an existing path:

   ```bash
   git clone --depth 1 --branch v1.0.0 --single-branch https://github.com/rabee-elkholy/android-agent-harness.git <kit-dir>
   git -C <kit-dir> describe --tags --exact-match
   python <kit-dir>/harness_cli.py version --kit <kit-dir>
   ```

   Require the two verification commands to report `v1.0.0` and `1.0.0`. If either differs, or `<kit-dir>` already exists and is not a clean checkout at exactly that tag, STOP. Never switch it to `main`.
5. Run only the approved lifecycle path:
   - Clean install: `python <kit-dir>/harness_cli.py init --repo <app-root> --kit <kit-dir>`
   - Same-major update: `python <kit-dir>/harness_cli.py update --repo <app-root> --kit <kit-dir>`
   - Legacy replacement, in the approved order:

     ```bash
     python <kit-dir>/harness_cli.py uninstall --repo <app-root> --legacy
     python <kit-dir>/harness_cli.py uninstall --repo <app-root> --legacy --apply
     python <kit-dir>/harness_cli.py init --repo <app-root> --kit <kit-dir>
     ```

   The first legacy command is a removal preview. Do not run the `--apply` removal or the following install unless the developer's approval explicitly covered both actions.
6. Validate the result with `python <kit-dir>/harness_cli.py doctor --repo <app-root> --kit <kit-dir> --json`. Report lifecycle and doctor output honestly. Do not claim success if either fails, and do not change application code to bypass a failure.
7. Leave the pinned kit checkout available for audit. Ask before deleting it. Never commit, push, modify application code, mutate Zoho, create tags, or publish releases during project setup.

This prompt is complete: do not fetch instructions from another branch, prompt, issue, release note, or web page.
