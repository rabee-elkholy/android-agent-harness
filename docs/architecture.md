# Android Agent Harness: Architecture Guide

The **Android Agent Harness** is an enterprise-grade delivery gate and governance system designed to transform AI coding assistants from unconstrained code generators into disciplined, architecture-compliant engineering teammates.

---

## System Topology

```mermaid
graph TB
    subgraph Client ["Client Android Project"]
        IDE["AI Assistant / IDE (Cursor / Antigravity / Claude)"]
        FS[".agents / Workspace Rules"]
    end

    subgraph Governance ["Harness Governance Engine"]
        SafetyHooks["pre_tool_safety.py & hooks.json"]
        StateManager["_hook_state.py (Ephemeral State)"]
        Preflight["preflight_check.py (Lint + Room + Strings)"]
        GradleStream["run_gradle_task.py (Live Heartbeat)"]
        DeviceRunner["run_device.py (Adb / Live Activity)"]
    end

    subgraph Reviewers ["Parallel 5-Leaf Review Gate"]
        R1["Bug & Null-Safety Reviewer"]
        R2["Architecture & Convention Reviewer"]
        R3["Security & Permissions Reviewer"]
        R4["Perf & ANR Guardian Reviewer"]
        R5["Regression Impact Reviewer"]
    end

    subgraph Specialists ["On-Demand Dedicated Specialists"]
        S1["QA Diagnostics Agent (Logcat / ANR)"]
        S2["Android UI Expert (Compose / RTL)"]
        S3["Test Quality Specialist (*Test.kt Suites)"]
    end

    subgraph Integrations ["Ecosystem Integrations"]
        ZohoMCP["Zoho Sprints MCP Server"]
        GitGuard["Git Mutation Interceptor"]
    end

    IDE --> SafetyHooks
    SafetyHooks --> StateManager
    SafetyHooks --> GitGuard
    SafetyHooks --> Reviewers
    SafetyHooks --> Specialists
    Reviewers --> Preflight
    Specialists --> Preflight
    Preflight --> GradleStream
    GradleStream --> DeviceRunner
    DeviceRunner --> ZohoMCP
```

---

## Core Pillars

### 1. Shift-Left Proactive Quality Invariants
The Harness enforces proactive quality standards before any code is written, ensuring the Primary Lead Agent achieves first-pass approval from reviewers:
- **Null-Safety & Network Resiliency**: Coroutine exception handling (`IOException`, `SocketTimeoutException`), no `!!`, safe error propagation.
- **Clean Architecture**: MVI StateFlow as single source of truth, zero inline FQCNs, explicit top-level imports.
- **Accessibility & Compose**: Mandatory `contentDescription` on non-decorative images/icons, touch targets >= 48dp, dual-locale `@Preview` (en/ar).
- **Performance & Battery**: Zero I/O on `Dispatchers.Main`, sensor unregistration in `onPause()`/`DisposableEffect.onDispose`, Android 14 foreground service rules.
- **Database Migrations**: Mandatory version bump and explicit `Migration(old, new)` on any `@Entity` schema modification.

---

### 2. The Five-Leaf Review Gate
Unlike traditional assistants that output unreviewed code, the Harness intercepts tool execution until **5 specialized reviewer subagents** evaluate the review package in parallel:

1. **`bug-reviewer-agent`**: Detects memory leaks, unchecked `NullPointerExceptions`, coroutine race conditions, uncaught network/I/O timeouts, and missing error state propagation.
2. **`convention-reviewer-agent`**: Enforces strict MVI / Clean Architecture, single source of truth StateFlows, accessibility standards (`contentDescription`, 48dp touch targets), and KMP commonMain cleanliness.
3. **`security-reviewer-agent`**: Inspects exported components, permission declarations, SQL injection, and secret leakage.
4. **`perf-anr-guardian-agent`**: Prevents main-thread blocking operations, unoptimized recompositions, unreleased WakeLocks, sensor listener leaks, and Android 14 foreground service violations.
5. **`regression-impact-reviewer-agent`**: Maps the exact blast radius of changes to ensure dependent screens and ViewModels remain unbroken.

---

### 3. Dedicated On-Demand Specialists
Specialists dispatched only when specific forensic, UI, or test quality tasks are needed:
- **`qa-diagnostics-agent`**: Physical device Logcat forensic analysis and ANR root-cause investigation.
- **`android-ui-expert-agent`**: Jetpack Compose and legacy XML UI layout, theming, RTL, and responsiveness.
- **`test-quality-reviewer-agent`**: Audits unit and UI test suites (`*Test.kt`), verifying assertion depth, mocking integrity, and Coroutine `runTest` dispatchers:
  - Verifies non-vacuous assertions and full MVI state transition coverage (`Loading` -> `Success` / `Error`).
  - Enforces `StandardTestDispatcher` injection over hardcoded `Dispatchers.IO` / `Dispatchers.Main`.
  - Verifies Turbine sequential assertions for reactive `StateFlow` and `SharedFlow` streams.
  - Audits in-memory Room database DAO tests and `MigrationTestHelper` assertions.

---

### 4. Safety Interceptors & Git Mutation Protection
The harness intercepts destructive commands before they execute:
- **`git commit` / `git push`**: Hard blocked from autonomous execution. Developers retain sole authority over repository history (unless explicitly authorized via `I.3`).
- **`adb monkey` / `pm clear`**: Blocked to protect developer device state and prevent data wiping.
- **Anti-Polling Guardrails**: Limits tool poll loops (`>2` polls) to prevent infinite agent spin and enforce event-driven reactive wakeups.

---

### 5. Live Gradle Streaming (`run_gradle_task.py`)
AI assistants frequently get stuck or timeout when running long Gradle builds. `run_gradle_task.py` executes Gradle with a **10-second heartbeat monitor**, streaming build output and capturing structured diagnostics if compilation fails.

---

### 6. Zoho Sprints MCP Integration
Provides bidirectional synchronization with Zoho Sprints:
- Automatically reads bug descriptions, steps to reproduce, and attachments.
- Creates hierarchical tasks and subtasks.
- Posts Arabic/English QA testing handoff comments with the exact Git commit hash for complete audit traceability.

---

### 7. 12-Dimension System Doctor (`harness_doctor.py`)
Provides deterministic, end-to-end verification of repository health across 12 operational dimensions:
- Host & environment (Python runtime, Gradle wrapper, Android SDK path, Git status).
- File topology & version alignment (`.agents/VERSION`, `harness-rules.md`, 24 core scripts).
- Complete subagent roster (all 8 subagents with active security fingerprints).
- Product configuration (`_product.py`, package prefix, application ID, source root, assemble task).
- Template leakage check (verifying zero un-replaced `{{...}}` tokens in `.agents/`).
- Domain skills & workflow playbooks (verifying all 10 workflow playbooks and 7 reference guides).
- Multi-IDE tool adapter parity (`AGENTS.md` and tool-specific rule configuration).
- Safety hooks & atomic state locking (cross-platform atomic `state_lock()`, zero selftest failures).
- Process streaming & heartbeat (line-buffered standard I/O and process tree lifecycle termination).
- Preflight verification pipeline (string parity & hardcoded UI text, Room migration graph, fast Kotlin lint).
- Zoho Sprints MCP security boundaries (zero token leakage in repository).
- Connected devices & ADB hardware diagnostics (querying physical devices, emulators, and Android API levels).