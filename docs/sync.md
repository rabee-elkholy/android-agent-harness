# Maintaining kit and installed projects

The repository contains the portable release source. Each Android project has
its own installed `.agents` engine, product identity, local state, ownership
manifest, and preserved tailoring. Never copy an installed tree into this kit
or copy the kit's `agents/` directory manually into a project.

## Kit to project

Publish a validated compatible v1 release, then run the lifecycle updater in
the project. It validates release checksums, refuses modified managed files,
preserves allowed tailoring, stages the replacement, and rolls back on failure.

## Project fix to kit

Reproduce the issue in a clean fixture, patch the generic source here, add an
offline regression test, and run the complete selftest/release validation.
Remove product names, package IDs, launchers, credentials, state, screenshots,
and domain-only assumptions before proposing the change.

## Never synchronize

- `.agents/state/`, `.harness-backup/`, `.harness-recovery/`;
- `_product.py` values from a real application;
- `local.properties`, keystores, tokens, provider JSON, or user IDE config;
- approval, reviewer, gate, APK, or tracker evidence from another checkout.

Project references and Zoho workflow defaults are preserved by the updater but
cannot weaken the v1 kernel or evidence rules.
