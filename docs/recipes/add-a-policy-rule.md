# Recipe: Add a policy rule (new deny class)

Registration points verified against kit v0.12.0 code.

1. Add the verb/pattern to the canonical vocabulary in
   `agents/scripts/policy_vocab.py`: `GIT_MUTATIONS`, `DEVICE_BOUND_ADB`,
   `DENIED_PM_OPS`, `FORBIDDEN_TOOLS`, or `EMULATOR_PATTERNS` /
   `SHELL_INDIRECTION_PATTERNS`. Add a human label to `REASON_CODES` and, if
   needed, a classifier tuple in `_CLASSIFIERS`.
2. Implement the deny in `pre_tool_safety.py` (`handle_run_command` or the
   relevant handler). Keep every existing allow case untouched and make the
   check deterministic on the normalized command.
3. Keep the Antigravity grants example in parity when the rule is a
   command-level class: `templates/gemini-runtime/config.grants.example.json`.
   The selftest proves vocabulary/grants parity automatically, so a missing
   grants row fails CI.
4. Add regression coverage in `_hook_selftest.py` `cases` (deny AND the
   nearest allow neighbor) plus adversarial laundering variants (chained,
   spaced, flag-wrapped, homoglyph) as `security_*` assertions in
   `_security_selftest.py`.
5. Document the attack class: add a row to the `SECURITY.md` threat table
   mapping it to the new test names; extend `docs/threat-model.md` if it
   changes agent-behavior guidance; append a CHANGELOG entry under
   `[Unreleased]`.

Acceptance check:

```
python agents/scripts/_hook_selftest.py        # Total test failures: 0
python agents/scripts/_security_selftest.py    # Security selftest failures: 0
```
