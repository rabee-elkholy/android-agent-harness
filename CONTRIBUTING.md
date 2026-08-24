# Contributing to Android Agent Harness

Thank you for your interest in contributing to **Android Agent Harness**.

We welcome contributions from the Android, Kotlin Multiplatform, and software engineering communities -- whether it is adding new AI tool adapters, expanding subagent review heuristics, improving Python test runners, or polishing documentation.

---

## Code of Conduct

Please review and abide by our [Code of Conduct](CODE_OF_CONDUCT.md) in all project interactions.

---

## Development Setup

1. **Prerequisites**:
   - Python 3.10+ installed.
   - Git installed.
   - Android SDK / ADB (optional, for device runner testing).

2. **Clone the Repository**:
   ```bash
   git clone https://github.com/rabee-elkholy/android-harness-kit.git
   cd android-harness-kit
   ```

3. **Verify Self-Tests**:
   Ensure all existing tests pass on your machine:
   ```bash
   python agents/scripts/_hook_selftest.py
   python agents/scripts/preflight_check.py
   ```

---

## Architectural Principles

When contributing code, rules, or subagents, keep these core principles in mind:

1. **Zero Silent Regressions**: Every code modification in client projects must be verifiable. Safety hooks must fail closed.
2. **Deterministic Governance**: Tool blocks, subagent verifications, and git protections must be deterministic and testable in `_hook_selftest.py`.
3. **No Hardcoded Secrets**: MCP servers, API tokens, and webhook configurations must always use local `.env` or placeholder configurations. Never commit API keys.
4. **Bilingual Awareness**: Support RTL / Arabic string parity and Jetpack Compose `@Preview` guidelines across all templates.

---

## Testing Your Changes

Every new safety hook, subagent definition, or installer flag MUST include automated tests in `agents/scripts/_hook_selftest.py`.

Run the self-test suite:
```bash
python agents/scripts/_hook_selftest.py
```
Ensure output finishes with:
```
Total test failures: 0
```

---

## Commit Conventions

We follow [Conventional Commits](https://www.conventionalcommits.org/):
- `feat(subagents): add accessibility audit reviewer`
- `fix(hooks): prevent duplicate hash lockout on define_subagent`
- `docs(readme): add interactive architecture workflow`
- `test(selftest): add test case for git branch protection`

---

## Release Governance & Formatting Invariants

1. **Milestone Consolidation**: Do not create fragmented micro-releases for intermediate commits. Consolidate sprint improvements into clean minor/major milestone releases (`v0.1.0`, `v0.2.0`, `v0.3.0`, `v0.4.0`, `v0.5.0`, `v0.5.1`).
2. **Safe Release Creation (`--notes-file`)**: Always write release notes to a clean UTF-8 markdown file and publish using `gh release create <tag> --notes-file <file>`. Never pass multiline markdown as command-line strings to avoid PowerShell/Bash escape character corruption.
3. **Zero Emojis**: Maintain strict technical typography with zero casual emojis across all documentation, commits, and release notes.
4. **Automated Verification**: All changes must satisfy `_hook_selftest.py` with 0 failures before opening a PR.

---

## Submitting a Pull Request

1. Create a feature branch (`git checkout -b feat/your-feature-name`).
2. Implement your change with clean code and comments.
3. Add tests to `_hook_selftest.py` and run tests.
4. Update `CHANGELOG.md` under an `[Unreleased]` or target release section.
5. Push your branch and open a PR with the [Pull Request Template](.github/PULL_REQUEST_TEMPLATE.md).