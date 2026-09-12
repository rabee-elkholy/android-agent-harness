# Stability-first dogfooding

Keep the existing classifier, central policy, evidence store, and lifecycle as the
single delivery authority. Freeze architecture while validating the current
harness on ordinary work in one configured Android project. Fix demonstrated
defects within approved scope; do not add an orchestration provider, another
approval cycle, reviewer quotas, or mandatory reporting infrastructure.

## Local maintenance acceptance

- Run `python harness_cli.py selftest` and
  `python -m compileall -q harness_cli.py agents/scripts` on a stable working tree.
- Run `python scripts_dev/validate_release.py` after regenerating payload checksums
  with `python scripts_dev/generate_release_checksums.py` when payload files change.
- For device prerequisite policy, retain rejection of an omitted unit gate even
  with a recomputed policy hash and valid preflight evidence; retain rejection of
  missing required unit evidence and acceptance of matching complete evidence.
  These fixtures test prerequisites, not a physical installation.
- Upgrade a previous installation with both unchanged defaults and tailored
  references. Defaults must refresh, tailoring must survive, and differing
  preserved references must be reported for reconciliation.
- Release preparation builds in a temporary workspace and leaves existing build
  artifacts intact. Push the release commit, await CI for that exact commit,
  then tag and await tag validation before publishing. `--no-push` creates no tag;
  `--skip-tests` is only available for dry runs. PyPI uploads recheck both workflows.

## Real-project observations

Use naturally occurring, approved tasks; do not create artificial production
changes just to fill this list. Follow the project's configured modules, variants,
locales, targets, and policy-selected verification.

| Work encountered | Observe |
| --- | --- |
| Small strings or UI change | Correct resource ownership, supported locales, relevant UI states, and proportionate policy routing |
| Logic regression | Independent expected result, observed failure reason, and a nearby valid case |
| Compose issue | Actual recomposition evidence and valid state contracts, without automatic annotation changes |
| Fix after review | Findings resolved, immediate regressions checked, unrelated ideas recorded as DEFER |
| Build or device environment failure | Correct task/artifact selection and an honest environment limitation, without bypasses |

Use existing task notes to capture the task, harness version, host/model, selected
gates/reviewers, result, friction, and unresolved evidence limits. Record time or
token cost only when measured; do not infer savings from reviewer count. Library
and KMP targets require their own applicable checks, not an assumed app install.

Real-device results, CI success, and comparative model quality remain unproven
until actually observed. Publication and tracker updates retain their separate
authorization requirements.
