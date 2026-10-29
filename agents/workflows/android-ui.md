# Antigravity Android CLI UI diagnostics

Use only on Antigravity with the official `android-cli-plugin` already enabled.
This optional adapter does not install/update tools, start emulators, pair ADB,
install APKs, grant permissions, automate purchases, or alter review policy.
Other hosts retain the existing portable verification path.

## Fast Compose loop

1. Complete graph-backed discovery and obtain normal task approval. During
   IMPLEMENTING, keep previewable UI separate from ViewModel/network access and
   provide deterministic sample state. Add previews only in approved source scope.
2. Run `python .agents/harness.py android-ui capabilities --json` once. Unsupported
   options are an optional-tool blocker, never a reason to update automatically,
   modify application code to hide tool failure, or skip existing gates.
3. Run `python .agents/harness.py android-ui list --reference :<resolved-module>`.
   This compiles; reuse its result instead of rediscovering on every edit.
4. Select exact discovered FQNs for changed components and their affected screens.
   Run `python .agents/harness.py android-ui render --reference :<resolved-module> --fqn <exact-fqn>`.
   Repeat `--fqn` for up to 16 previews in one build. Do not render the whole app
   after each keystroke. Batch coherent edits, then render.
5. Component-tree JSON is the default. Read bounded relevant nodes from the returned
   paths; do not dump entire trees into context. Add `--image` when judging colors,
   clipping, spacing or visual appearance. A tree is not visual approval.
6. The renderer daemon is reused by default; `--no-daemon` requests one-shot work
   for memory-constrained sessions. The CLI documents a ten-minute idle shutdown.
   Use `--refresh` after a tool/environment change or to bypass advisory reuse.

Select relevant preview states: normal, loading, empty and error; Arabic RTL and
English; long text, large font and narrow width. Changes to shared themes/components
need representative dependent screens. Do not build a Cartesian product of every
locale, state and device. XML-only changes use existing verification.

The default module is derived from configured assemble, never assumed to be :app.
The Android CLI resolves its own preview variant: this adapter does not invent a
variant flag or claim that preview rendered the configured production APK. For
flavor-specific behavior use the configured harness assemble and physical-device
checks; treat previews as structural diagnostics until the CLI proves that variant.

## Physical phone loop

Follow normal routed tests/reviews, assemble and `device install-start`. After
successful fresh install and launch, run `python .agents/harness.py android-ui hub`.
The adapter selects the connected physical phone whose serial hash matches both
install and launch evidence. `--serial` can assert that choice, never override it.
Disconnect, wrong phone, changed APK/snapshot, mismatched Android user, or stale
proof blocks opening. There is no emulator or alternate-phone fallback. The command
returns within seconds (the hub keeps serving in the background) together with the
`[Android Device Hub](sidecar://android-cli-plugin/device-hub/)` pill; if the
Device Hub pane is already mirroring the phone, show the pill instead of reopening.

To inspect or drive the screen during verification, never call `android layout`,
`android screen` or `adb` directly (they are not bound to the verified build and
the guard refuses them). Use `python .agents/harness.py e2e observe` (compact
element list), `e2e screenshot` (PNG to view), and `e2e tap/type/key/swipe/wait/restart`
inside a phone E2E session (`.agents/workflows/phone-e2e.md`). `observe` and
`screenshot` bind the verified phone on demand.

Reuse the open Hub window for the walkthrough. Do not repeatedly launch windows or
stream screenshots into the model. Capture only relevant milestones/failures using
existing harness capture tools. Test Back/navigation, keyboard, rotation, permissions
and real services on the phone as applicable. Human Hub interactions are not
automated journey proof: preserve explicit walkthrough/sign-off and approved journey
contracts. Hub can download its extension pack on first launch; it does not imply a
successful connection or UI test. Close the window when live mirroring is unnecessary.

## Resource and evidence contract

- Preview and existing Gradle execution share a fail-fast per-worktree lock.
- Diagnostics are local under `.agents/state/diagnostics/android-ui`, never gate
  results. At most twelve adapter output directories are retained.
- Advisory reuse lasts at most ten minutes and binds repository/task/plan, full
  delivery source/resource/build inputs, external inputs, CLI identity, selected
  FQNs/options and relevant environment. Every output hash is rechecked. Changes
  during rendering reject reuse. Use refresh for untracked external tool changes.
- Output capture and printed file lists are bounded. Full component trees and images
  remain files. Keep real user data, credentials and sensitive screenshots out of
  evidence; previews should use synthetic data.
- `DIAGNOSTIC_OK` and `OPEN_REQUESTED` are never PASS evidence. No new completion
  authority, risk router or required verification gate is introduced.

Official command references:
- https://developer.android.com/tools/agents/android-cli/commands/preview_list
- https://developer.android.com/tools/agents/android-cli/commands/preview_render
- https://developer.android.com/tools/agents/android-cli/commands/device_hub
