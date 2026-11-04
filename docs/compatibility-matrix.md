# Compatibility matrix

## Validated product boundary

| Dimension | Supported shape | Behavior outside the boundary |
|---|---|---|
| Build | Gradle Wrapper; Kotlin/Groovy DSL | Non-Gradle Android builds are refused |
| Code | Native Android (`Kotlin`, `Java`, `Compose`, `XML`, hybrid) & **KMM / KMP (Kotlin Multiplatform Mobile)** (`commonMain`, `androidMain`, `iosMain`, `expect`/`actual`, Compose Multiplatform, and iOS `.swift` graph & `task-context`) | Unknown material surfaces require a developer decision |
| Modules | Single-module Android, multi-module Android, library-only, dynamic feature, and **KMM / KMP topologies** (`:shared`, `:composeApp`, `:androidApp`, `:iosApp`) | Library-only projects disable APK/device gates |
| Variants | Default debug, discovered flavor, or exact combined variant entered during setup | Missing/ambiguous variant is a setup blocker |
| Architecture | Existing project architecture, DI, persistence, and conventions | The harness does not convert architecture implicitly |
| Tests | Repositories with tests, no tests, or explicit baseline debt | A required test gate cannot pass with zero executed tests |
| Device | Explicit physical/wireless ADB target; optional emulator policy | No automatic pairing, reconnect loop, data clear, or downgrade |
| Git | Normal checkout and worktree | Non-Git delivery evidence is unsupported |

## Runtime matrix

| Runtime | Declared support | Validation |
|---|---|---|
| Python 3.10–3.14 | Supported | The complete suite runs on Linux with Python 3.12; Python 3.10, 3.11, 3.13 and 3.14 run the `selftest --quick` subset on Linux |
| Linux, macOS, Windows | Supported | The complete suite runs on Linux; macOS and Windows run the `selftest --quick` subset with Python 3.12; wheel lifecycle tests run on all three |
| Python 3.15+ | Not yet declared | Refuse release claims until added to CI |

CI configuration is evidence only after it has actually run. A local doctor
must not report an unexecuted hosted matrix as passed.

## Host trust

| Tier | Meaning |
|---|---|
| `HARD_ENFORCED` | A host-native boundary intercepts the stated mutation class |
| `RULE_ENFORCED` | Rules and workflow apply, but technical bypass prevention is incomplete |
| `UNSUPPORTED` | Minimum safe workflow is unavailable |

Conversational plan approval is always reported as `RULE_ENFORCED` unless a
host supplies proof the agent cannot synthesize. See [Tool support](tool-support.md).

## External integrations

| Integration | Safety contract |
|---|---|
| Universal PM MCP (`zoho-projects_mcp`, `zoho-sprints`, `atlassian-mcp-server` / Jira, Linear, Monday.com, GitHub, ClickUp, Asana, Trello) | Runtime zero-config MCP discovery (`pm discover`); mandatory preview and developer approval (`pm authorize`); Bug/Issue descriptions protected from overwrite/empty replacement; no automatic `Done`/`Solved`/`Closed` without `--allow-close`; 5-section RTL/LTR QA reports with zero code-identifier leakage (`pm prepare-report`) |
| Google Workspace CLIs & Generic MCP Tools | Evaluated independently of code task plan state (`ADR-017`); read-only commands allowed; mutations route through host confirmation (`ask`/`force_ask`); secret and signing files hard-denied |
| Incident Reporting (`report-issue`) | Organized local Zero-PII JSON + Markdown bundles (`.agents/state/incidents/`); consent-first `ask_question` prompt before submitting allowlisted non-PII metadata to GitHub Issues (optional `--always-auto-submit`) |
