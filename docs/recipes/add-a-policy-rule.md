# Recipe: add a policy rule

1. Put deterministic change-surface detection in `change_classifier.py` or an
   immutable safety deny class in `pre_tool_safety.py`. Do not create a second
   policy vocabulary.
2. If the rule changes reviewers, gates, device requirements, or model cost,
   update only `review_policy.py` and its deterministic recomputation test.
3. Add the nearest allow neighbor plus chained, path, Unicode, malformed, and
   host-bridge cases to `_hook_selftest.py`/`_security_selftest.py`.
4. Update the threat model and changelog.

```bash
python agents/scripts/_vnext_selftest.py
python agents/scripts/_hook_selftest.py
python agents/scripts/_security_selftest.py
```

The rule must fail closed without turning normal read-only inspection into a
mutation or forcing an expensive gate for unrelated low-risk work.
