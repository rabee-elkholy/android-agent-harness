---
name: systematic-debugging
description: Use when diagnosing Android app bugs, crashes, regressions, or unexpected UI behavior. Requires explicit evidence and hypotheses before code changes.
version: 1.1.0
kernel-major: 1
---

# Systematic Debugging Skill

## 1. Root Cause Hypothesis Framework
Do NOT guess code fixes. Mandatory sequence for ALL bug, crash, or regression fixes:
1. **Gather Concrete Evidence**:
   - *Code / Test*: Failing deterministic unit/integration test, assertion failure, compiler error, lint violation.
   - *Runtime / Android*: Logcat excerpt, crash stacktrace, ANR trace, lifecycle reproduction, permission denial, DB migration error.
   - *Logic / State*: Invalid StateFlow/LiveData transition, race condition, wrong Coroutine dispatcher/scope.
2. **Formulate Explicit Hypothesis**: Identify the most likely root cause at the producer level.
3. **Plan Targeted Mutation**: Make the minimal fix directly addressing the root cause.
4. **Verify**: Prove the original failure is resolved and no regressions are introduced.

## 2. Prohibition of Symptom Swallowing
- Never resolve bugs by swallowing exceptions, adding empty `try-catch`, or returning fallback `0`/`null`/dummy data.
- Always fix the root condition at the data producer or state machine level.

## 3. EVIDENCE_LIMITED Escape Hatch
Not every bug can be reproduced locally (e.g. backend service dependencies, user-specific data, production telemetry, or specific hardware).
When local reproduction is genuinely impossible, enter `EVIDENCE_LIMITED` mode by recording:
1. **Known Evidence**: What is known with certainty from logs, telemetry, or reports.
2. **Unknown Assumptions**: What assumptions are being made.
3. **Fix Hypothesis**: Why the planned code change addresses the likely cause.
4. **Risk & Verification**: Potential side effects and how the developer should verify in production/staging.

Never stall indefinitely demanding impossible local reproduction when `EVIDENCE_LIMITED` conditions apply.
