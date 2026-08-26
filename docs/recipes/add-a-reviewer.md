# Recipe: Add a reviewer subagent

Registration points verified against kit v0.12.0 code.

1. Create `agents/subagents/<name>.json` with `name`, `description`,
   `model: "inherit"`, `workspace: "inherit"`, `enable_write_tools: false`,
   `enable_subagent_tools: false`, and a `system_prompt` whose FIRST line is
   `HARNESS_<X>_FINGERPRINT=<new-unique-version-tag>`. The fingerprint plus a
   verbatim normalized body match is what authorizes `define_subagent`
   (`_hook_state.py prompts_match`), so changing a prompt REQUIRES a new
   fingerprint value.
2. Register the fingerprint in `harness_doctor.py` `CORE_SUBAGENTS` so the
   doctor's dimension-3 roster check validates it.
3. Allow-list the name in `pre_tool_safety.py`:
   - Specialist (on-demand): add to `ALLOWED_KINDS` only.
   - Delivery leaf: add to BOTH `ALLOWED_KINDS` and `REVIEW_FIVE` â€” this
     changes the barrier to six leaves and must be called out in the ADR and
     CHANGELOG.
4. Optional alias: `_hook_state.py` `TEMPLATE_ALIASES`.
5. Add tests in `_hook_selftest.py`: load the template prompt next to the
   other PROMPT_* constants, then add a `("define_<x>_ok", define(PROMPT_X,
   name="<name>"), "allow")` case in `cases`, an invoke case for specialists,
   and (for delivery leaves) update every five-leaf dispatch helper.
6. Update docs (`README.md` leaf table if a delivery leaf, roster lists in
   `docs/architecture.md`) and append a CHANGELOG entry under `[Unreleased]`.

Acceptance check:

```
python agents/scripts/_hook_selftest.py   # ends with: Total test failures: 0
python harness_cli.py doctor --json       # failures: 0 (dimension 3 roster passes)
```
