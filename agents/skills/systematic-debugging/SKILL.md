---
name: systematic-debugging
description: Use when diagnosing Rashaqa Android bugs, crashes, or unexpected UI behavior. Requires explicit hypotheses before code changes.
---

# Systematic Debugging Skill (Superpowers Protocol)

## 1. Root Cause Hypothesis Framework
Do NOT guess code fixes. MANDATORY for ALL bug fixes without exception:
1. **Formulate Explicit Hypotheses**: List 2–3 potential causes.
2. **Isolate State & Triggers**: Trace data flow from trigger to failure point.
3. **Log & Trace Inspection**: Read full un-truncated stack trace or ADB logcat before forming conclusions.
4. **Reproduce & Test Hypothesis**: Verify hypothesis against empirical evidence before modifying code.

## 2. Prohibition of Symptom Swallowing
- Never resolve bugs by swallowing exceptions, adding empty `try-catch`, or returning fallback `0`/`null` dummy data.
- Always fix the root condition at the data producer level.
