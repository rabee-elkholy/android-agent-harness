# Scoped re-review user prompt (policy-selected reviewers)

After fixes and required deterministic checks, regenerate the package and dispatch only the reviewers selected by the central later-round policy. Preserve its snapshot/evidence binding and round limits; this prompt does not select reviewers or relax final verification.

```
HARNESS_REVIEW_PACKAGE=[PATH from python .agents/scripts/review_package.py]
HARNESS_PACKAGE_SHA256_12=[12-hex digest printed by review_package.py]
This is a scoped re-review of the fix diff.

Previous findings to verdict:
- [finding 1]
- [finding 2]

Verdict each finding ADDRESSED or NOT ADDRESSED with file:line. Flag new breakage. If the previous items are addressed and your leaf is clean, emit your PASS token (BUG_PASS / CONVENTION_PASS / SECURITY_PASS / PERF_PASS / REGRESSION_PASS).

Focus on the fixes, their immediate consumers, and regressions caused by them. Record unrelated improvements as DEFER without turning them into blocking scope expansion. A newly discovered in-scope correctness or safety defect remains actionable. State the inspected scope and evidence limits; do not claim whole-application correctness from a scoped review. Use the selected reviewer's own verdict format, including the test-quality reviewer when policy selects it.

End your reply with the evidence footer:
`EVIDENCE pkg=<HARNESS_PACKAGE_SHA256_12> cites=<n>` where <n> is your citation count
(cites=0 for a clean PASS). A reply without a valid matching footer does not clear
the delivery barrier.
```
