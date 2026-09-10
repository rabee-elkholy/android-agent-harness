<!-- managed-by: android-agent-harness -->
# Android Agent Harness repository instructions

The compact source of truth is `agents/rules/harness-rules.md`. Read it before changing this repository.

This checkout is the harness kit itself, not a client Android application:

- use `python harness_cli.py selftest` for the complete deterministic suite;
- use `python -m compileall -q harness_cli.py agents/scripts` for syntax validation;
- do not run Android Gradle or ADB gates against this repository;
- keep runtime code Python standard-library only;
- keep code, rules, prompts, documentation, and commit messages in English;
- preserve Zoho Sprints behavior, but never perform a live tracker mutation without `update zoho`;
- leave changes unstaged unless the maintainer explicitly asks for Git operations;
- do not publish or tag a release until release validation and CI pass.

The approved vNext implementation plan authorizes the complete stated scope without phase-by-phase stops. Material expansion outside that plan still requires revised approval. Follow-ups and technical fixes within active scope require immediate execution without plan re-drafting or waiting for nonexistent Proceed buttons.
