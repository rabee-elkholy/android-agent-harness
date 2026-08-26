# Recipe: Add a tool adapter

Registration points verified against kit v0.11.0 code.

1. Create `agents/tool-adapters/<tool>.template` using the fill placeholders
   `{{PRODUCT}}`, `{{PY}}`, `{{ASSEMBLE}}`, `{{DEVICE_POLICY}}`, and
   `{{GIT_POLICY}}` (see `pointer.md.template` for the minimal shape).
2. Register output paths in `install_tool_adapters.py`:
   - Add the generated file list to `TOOL_FILES[<id>]`.
   - Add a body branch in `bodies_for_tool` (or fall through to the pointer).
   - Optional aliases in `TOOL_ALIASES`; cleanup dirs in
     `EMPTY_DIR_CANDIDATES`.
3. Register the wizard id and EN/AR labels in `setup_wizard.py` `TOOL_IDS` /
   `TOOL_LABELS` so question I.14 offers it (multi-select pre-fill included).
4. Update docs: the adapter matrix and tier tables in `docs/tool-support.md`,
   the template list in `agents/tool-adapters/README.md`, and a CHANGELOG
   entry under `[Unreleased]`.
5. If the tool ships a native hook protocol, model the bridge on
   `cc_pre_tool_safety.py` (always exit 0, decision in stdout JSON,
   fail-closed on garbage input), register it like `ensure_cc_hooks`, and add
   bridge parity cases to `_hook_selftest.py` / `_security_selftest.py`.

Acceptance check:

```
python agents/scripts/install_tool_adapters.py --repo <fixture-checkout> --product Test --py python --assemble :app:assembleDebug --tools <id>
python agents/scripts/_hook_selftest.py   # Total test failures: 0
```

The installer writes exactly the selected adapters (plus `AGENTS.md`), and
the doctor reports the adapter under dimension 7.
