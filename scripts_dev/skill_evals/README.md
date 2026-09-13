# Skill Pressure Testing & Behavioral Evaluations

## Purpose

Deterministic unit tests in Android Agent Harness (`harness_cli.py selftest`) prove that Python kernels, file classification, cryptographic hashes, and verification gates work correctly.

However, deterministic tests cannot prove that **natural language skills** (`SKILL.md`) actually guide AI coding agents when agents are subjected to realistic development pressure (e.g. developer requesting a "quick fix", incomplete logcats, build timeouts with stale APKs present, or temptations to skip unit tests).

This directory provides developer-side quality engineering tooling to pressure-test agent skills **without adding runtime overhead or model dependencies for client Android tasks**.

---

## Architectural Rules

1. **Strictly Developer-Side**: This framework is used during harness development and release qualification. It is **never** invoked during normal Android app tasks.
2. **Decoupled from Selftest**: Does not run inside `harness_cli.py selftest`.
3. **No Network/API Gate**: Evaluating mock transcripts or schemas requires standard library only.
4. **Transparent Case Schema**: Evaluation cases in `skill_eval_cases.json` specify:
   - `skill`: Targeted skill identifier.
   - `scenario`: Realistic Android context.
   - `pressure`: Shortcuts or constraints encouraging the agent to violate guidelines.
   - `required_behaviors`: Expected engineering actions.
   - `forbidden_behaviors`: Specific bad practices that must not occur.

---

## Running Case Validation

To validate that all evaluation cases are well-formed and match current skill files:

```bash
python scripts_dev/skill_evals/skill_eval_runner.py --lint-only
```
