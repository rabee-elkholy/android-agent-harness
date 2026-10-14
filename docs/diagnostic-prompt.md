# Diagnose Android Agent Harness

> **Raw Prompt URL**: `https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.1.26/docs/diagnostic-prompt.md`
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness`
> **Kit version**: `v1.1.26` — **SHA-256**: `4f1457e168627137a1430da6f5ec89c9937cd8fdcb9ee422fe88f99986ad642c` (SHA-256 of every byte after this line; verify first — mismatch = STOP)

---
Before executing anything: verify that the SHA-256 of every byte after the **SHA-256** header line equals the header value. If it does not match, STOP and tell the developer the file was tampered with.

Run a read-only diagnosis at the Android project root:

1. `python harness_cli.py doctor --repo <app> --kit <kit> --json` (or `python .agents/harness.py doctor --json`).
2. Verify Antigravity-first installation dimensions:
   - `.agents/hooks.json` presence and valid schema;
   - All 7 routed Antigravity reviewer agent definitions under `.agents/agents/<reviewer>/agent.md`;
   - Review Protocol V2 active configuration;
   - Antigravity trusted runtime root resolver (CLI, IDE, and 2.0 roots);
   - Mutation hook coverage including `multi_replace_file_content`, `replace_file_content`, and `write_to_file`;
   - PostToolUse invoke reconciliation hook;
   - Semantic host identity (`antigravity`);
   - Reviewer model inheritance-by-omission;
   - Reviewer Call Safety Cap (default 20).
3. If issues are identified, report the exact diagnostic failure. Never suggest manually editing or patching `.agents/**` files in the Android project. Run `python harness_cli.py repair --repo <app> --kit <kit>` to cleanly restore managed engine files.
4. Do not browse installed engine source to interpret ordinary gate failures, scope denials or reviewer budgets. If an unexpected engine failure or explicit developer inspection request requires source, use `python .agents/harness.py doctor --inspect-file scripts/<exact-file>.py --inspection-reason <unexpected_failure|contract_violation|doctor_issue|developer_request> --reference "<concrete output/request>" --inspect-start-line <line> --inspect-lines <1-200>`. Read only the relevant excerpt; this diagnostic command grants no mutation or delivery authority.
