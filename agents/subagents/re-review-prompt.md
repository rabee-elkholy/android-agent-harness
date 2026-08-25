# Scoped re-review user prompt (all 5 leaves)

After fixes, regenerate the package (content must change) and dispatch the **same 5** in one invoke.

```
HARNESS_REVIEW_PACKAGE=[PATH from python .agents/scripts/review_package.py]
HARNESS_PACKAGE_SHA256_12=[12-hex digest printed by review_package.py]
This is a scoped re-review of the fix diff.

Previous findings to verdict:
- [finding 1]
- [finding 2]

Verdict each finding ADDRESSED or NOT ADDRESSED with file:line. Flag new breakage. If the previous items are addressed and your leaf is clean, emit your PASS token (BUG_PASS / CONVENTION_PASS / SECURITY_PASS / PERF_PASS / REGRESSION_PASS).

End your reply with the evidence footer:
`EVIDENCE pkg=<HARNESS_PACKAGE_SHA256_12> cites=<n>` where <n> is your citation count
(cites=0 for a clean PASS). A reply without a valid matching footer does not clear
the delivery barrier.
```
