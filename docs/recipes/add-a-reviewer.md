# Recipe: add a reviewer

1. Add `agents/subagents/<role>.json` with read-only tools, inherited workspace,
   inherited model, a stable role name, and an evidence-focused prompt.
2. Register the role only for justified surfaces in `review_policy.py`. Do not
   add it to every task by default.
3. Add its fingerprint to `doctor/models.py` when it is a shipped core role.
4. Extend `record_review.py` verdict/token compatibility only when needed.
5. Test exact selection, missing/extra roster denial, malformed findings,
   package mismatch, model escalation denial, and the three-round cap.

```bash
python agents/scripts/_vnext_selftest.py
python agents/scripts/_hook_selftest.py
python harness_cli.py doctor --json
```

A reviewer never creates developer approval and cannot approve a package it did
not inspect.
