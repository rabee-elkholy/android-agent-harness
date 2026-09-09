---
description: Diagnose and fix an Android defect under an explicitly approved plan.
---

# Debug an Android defect

1. Read evidence and, when present, fetch the Zoho item read-only. Form two or three testable hypotheses.
2. Reproduce the defect with the smallest useful test or device evidence. Analysis remains read-only until the developer approves the plan.
3. After approval, fix the producer-level cause; do not hide errors with empty catches or dummy fallbacks.
4. Let the classifier select skills, tests, reviewers, build, and device verification. A test change adds the test-quality reviewer; sensitive surfaces select the full review set and approval evidence.
5. Follow `deliver.md` from verification preparation onward. Device/environment absence is `ENV_BLOCKED`, never a false success.

Zoho remains unchanged until the developer says `update zoho`.
