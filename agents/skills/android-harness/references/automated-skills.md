# Automated Multi-Agent Architecture & Skills Catalog

Canonical protocol: `.agents/rules/harness-rules.md`. This file does not add policy.

---

## 1. Complete Skills Catalog (8 Skills)

1. **`android-harness`**: Core governance, platform references, and daily checkout facts.
2. **`brainstorming`**: Interactive requirements exploration and 2–3 architectural options evaluation with trade-offs.
3. **`test-driven-development`**: Strict **RED-GREEN-REFACTOR** test-first methodology.
4. **`systematic-debugging`**: Root-cause hypothesis isolation and empirical reproduction.
5. **`compose-inspector`**: Jetpack Compose stability, recomposition optimization, and RTL localization.
6. **`kotlin-coroutines-expert`**: Structured concurrency, Flow lifecycles, and dispatcher safety.
7. **`gradle-build-optimizer`**: Gradle daemon, build cache, and compile speed optimization.
8. **`git-pr-automator`**: Safe conventional commit formatting and PR hygiene.

---

## 2. Review & Quality Gates

### Stage 0.5: Pre-Review Test Quality Gate
- **Trigger**: Automatically required whenever `*Test.kt` or `src/test/` files are modified or added.
- **Reviewer**: `test-quality-reviewer-agent` (runs independently first).
- **Checks**: Assertion depth ($\ge 2$), Coroutine `StandardTestDispatcher` control, and Mock isolation.
- **Verdict**: `TEST_PASS` required before advancing to Stage 1.

### Stage 1: Parallel 5-Leaf Review Gate (Mandatory)
One `invoke_subagent` call, five specialized leaves, same `HARNESS_REVIEW_PACKAGE`:
- `bug-reviewer-agent` → `BUG_PASS`
- `convention-reviewer-agent` → `CONVENTION_PASS`
- `security-reviewer-agent` → `SECURITY_PASS`
- `perf-anr-guardian-agent` → `PERF_PASS`
- `regression-impact-reviewer-agent` → `REGRESSION_PASS`

### Silent Review Wait Invariant
- During parallel review execution, the Lead Agent **remains 100% silent in chat** on intermediate subagent wakeups.
- The IDE interface displays native live progress cards and checkmarks.
- A single consolidated outcome summary is printed only after all 5 verdicts are in context.

---

## 3. On-Demand Specialists
- `qa-diagnostics-agent` — device logcat, crash & ANR forensics
- `android-ui-expert-agent` — Compose & legacy XML layout guidance
- `test-quality-reviewer-agent` — standalone test suite audits
