# Demo Media — Recording Guide

Placeholder directory for the README demo GIFs. Record each shot, export as
GIF at 1200px width, and drop the file into this directory with the exact
name referenced by the README demo table. Keep every shot under 30 seconds
and never show real credentials, tokens, or private code.

## Shot 1: `install.gif` — Install wizard end-to-end

1. Fresh terminal in an Android project root: `python harness_cli.py init`.
2. Show 3-4 wizard questions answered (backup, git policy, tools).
3. Paste the pinned install prompt into a new chat and show the structural
   port starting (facts table or backup line is enough).

## Shot 2: `review.gif` — Five-leaf dispatch + evidence footers

1. After an edit, run `python .agents/scripts/review_package.py` and
   highlight the printed `HARNESS_REVIEW_PACKAGE=` / `HARNESS_PACKAGE_SHA256_12=`.
2. Dispatch all five reviewers in one call; scroll their replies ending in
   `BUG_PASS ... EVIDENCE pkg=<hash> cites=<n>`.
3. Show `state/verdicts/verdict-<pkg12>.json` and run
   `android-harness verify --repo .`.

## Shot 3: `safety.gif` — Blocked commit + pre-commit gate

1. Agent attempts `git commit -m x`: show the hook's deny JSON.
2. Stage a string-parity violation, run `git commit`: show the pre-commit
   gate blocking with `[STRINGS]` findings.
3. Fix, restage, commit successfully.

## Shot 4: `doctor.gif` — 12-dimension doctor report

1. Run `python harness_cli.py doctor --json`.
2. Scroll the dimension results and the summary line
   (`Diagnostic Summary: N Passed ...`).

## Export tips

- macOS: `ffmpeg -i in.mov -vf "fps=12,scale=1200:-1" out.gif`
- Windows: record with Xbox Game Bar / ShareX, then convert with ffmpeg.
- Verify each GIF opens from the README demo table before publishing.
