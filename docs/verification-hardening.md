# Search scope, diagnostic retries, and startup observations

These checks extend the existing hook engine, test gate and device flow. They do not
add task states, reviewer dispatch steps, approval prompts or runtime dependencies.

## Search scope

A manifest, build file or resource in `expected_files` grants access to that exact
file. Its parent directory is not a recursive search grant. A planned or resolved
Kotlin/Java source file may grant its source package, preserving bounded sibling
and caller inspection. An ancestor directory or unrelated package requires a
Project Graph expansion. Whole-module discovery grants a module only when the
graph query explicitly targets that module.
Search targets are resolved against the repository, including `..` and symlinks,
before scope checks. A lexical prefix cannot grant access outside the package.

The same bounds apply while phase reviewers run during `IMPLEMENTING`; the task
does not need to pretend it has entered final `VERIFYING`. Frozen final-review
scope continues to use its existing scope checks. Existing exact-file reads remain
available. Stale graph receipts do not extend an active task's search scope.

Native tool interception depends on the detected host integration. The shared
engine rejects direct Gradle/ADB shell entry points; mentioning a wrapper filename
in the arguments or another command does not grant an exemption. This is a host
tool boundary, not an operating-system sandbox.

## Engine diagnostics

Native hooks intercept direct reads and searches of installed engine implementation,
including `view_file` on Antigravity and common shell reads. Rules, task plans,
evidence and application source remain readable. First run the documented command
and use its output. An ordinary application failure, scope denial or reviewer cap
does not justify browsing engine internals. Never create an empty test task to hide
a task-selection defect.

An unexpected engine failure, contract violation, Doctor issue or explicit developer
request can use a bounded read-only diagnostic command:

```sh
python .agents/harness.py doctor --inspect-file scripts/run_tests_gate.py --inspection-reason unexpected_failure --reference "Unit-test gate selected a missing task" --inspect-start-line 269 --inspect-lines 120
```

The command reads one exact Python file inside the selected engine, at most 200
lines, with path/size checks. It does not traverse dependencies, run device checks,
write evidence or grant mutation authority. The caller states the diagnostic
reason; this declaration is rule-enforced, not trusted failure or developer-approval
proof. Tool interception is not an operating-system sandbox.

## Module selection and reviewer spending

Changed-module unit-test selection excludes explicitly applied Android Asset Pack
plugins, which do not supply JVM unit-test tasks. Kotlin/Groovy and resolved catalog
aliases are supported. Comments, `apply false`, mixed test plugins and unresolved
convention logic do not suppress a module's conservative selection. Explicit task
arguments and legacy configured selection retain their existing authority.

The reviewer-call limit chosen during setup remains the shared task limit for all
phase calls, corrections and final review. Drafts disclose an advisory estimate of
up to two calls per non-documentation phase, the central policy's preliminary final
roster, and a correction reserve. Actual phase selection stays with central policy;
the estimate is not a guarantee that every later review will fit.

The forecast is displayed before initial approval. It does not rewrite setup
answers, change counters or create a second spending setting. A separate explicit
developer spending decision through the existing `task review-budget` command is
still required for any increase. Existing active tasks keep their approvals and
budgets. Scope-denial hints batch planned-file classification instead of repeating
repository inventories once per file; file/module-only denial skips that advisory
surface scan.

## One diagnostic unit-test retry

When the ordinary unit-test gate finds fresh, attributable `NEW_REGRESSION`
failures, it records the first verdict and failure fingerprints before Gradle can
replace the XML reports. It then reruns the selected tasks once through the same
Gradle wrapper, with `--rerun-tasks --no-build-cache`. Running the full selected
tasks preserves suite context and avoids guessing parameterized test filters.

The source snapshot, change set and external inputs must remain unchanged across
both attempts. Fresh exact-case PASS evidence on the retry produces
`SUSPECTED_FLAKY`; it does not approve delivery. Persistent failures, stale/missing
reports, changed inputs and environment failures remain blocking. Both attempt
summaries are retained in append-only gate evidence; raw failure messages are not
added to retry diagnostics. Investigate intermittent behavior before a new clean
verification run. The gate never updates the baseline itself.
Repeating the test command in the same verification run cannot erase its diagnostic
failure, and reusing that run's evidence cannot bypass the restriction. A fresh
verification run after investigation can establish new clean evidence.

Known baseline/task-start debt alone does not trigger a retry. `--capture-red`,
`--record-start` and `--record-unrelated` keep their original single-run semantics.

## Startup observations

`device start` and `device install-start` now check the actual installed APK member
checksums, selected device, foreground application and target Android user. They
reuse the journey ADB transport and UI hierarchy parser. The default total startup
budget is 15 seconds; `--startup-timeout` accepts 1 through 30 seconds. Read-only
startup observation does not navigate, dismiss permission dialogs, reconnect a
device, collect screenshots or replace the approved walkthrough.
Installed APK checksums are checked again after UI observation; a replaced package
cannot satisfy the startup assertion. Malformed, oversized or excessively deep UI
hierarchies produce no usable screen proof.

To assert a known startup element, supply its exact resource ID:

```sh
python .agents/harness.py device install-start --expect-resource-id com.example:id/home
```

The element must be unique, have non-empty bounds and belong to the verified app.
A missing, invisible or ambiguous element blocks launch verification. Unavailable
hierarchy/device/artifact proof cannot satisfy a requested element assertion.

Without an expected element, successful foreground/artifact checks establish only
that the verified app reached the foreground. The hierarchy result is diagnostic;
neither a non-empty hierarchy nor a successful launch proves the screen rendered
correctly. Missing accessibility exposure may be reported as `UNAVAILABLE` while
the manual walkthrough remains required. Evidence stores only sanitized outcomes
and an expected-selector hash, never the raw hierarchy or screen text.

The existing artifact/device/user/snapshot chain still binds launch evidence.
Legacy launch records without startup observations remain readable; a present
startup observation must have a supported schema and successful identity checks.
