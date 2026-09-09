# Compatibility matrix

## Validated product boundary

| Dimension | Supported shape | Behavior outside the boundary |
|---|---|---|
| Build | Gradle Wrapper; Kotlin/Groovy DSL | Non-Gradle Android builds are refused |
| Code | Kotlin, Java, mixed, Compose, XML, hybrid | Unknown material surfaces require a developer decision |
| Modules | Application, library-only, multi-module, dynamic feature, Android/KMP target | Library-only projects disable APK/device gates |
| Variants | Default debug, discovered flavor, or exact combined variant entered during setup | Missing/ambiguous variant is a setup blocker |
| Architecture | Existing project architecture, DI, persistence, and conventions | The harness does not convert architecture implicitly |
| Tests | Repositories with tests, no tests, or explicit baseline debt | A required test gate cannot pass with zero executed tests |
| Device | Explicit physical/wireless ADB target; optional emulator policy | No automatic pairing, reconnect loop, data clear, or downgrade |
| Git | Normal checkout and worktree | Non-Git delivery evidence is unsupported |

## Runtime matrix

| Runtime | Declared support | Validation |
|---|---|---|
| Python 3.10–3.13 | Supported | CI matrix is defined for Linux, macOS, and Windows |
| Linux, macOS, Windows | Supported | Local completion proves the current OS only; hosted CI is the cross-OS authority |
| Python 3.14+ | Not yet declared | Refuse release claims until added to CI |

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
| Zoho Sprints | Built-in stdio MCP; user-level credentials; plan-scoped writes; idempotent `operation_id`; no automatic Done/Solved/Closed |
| GitHub Projects | Optional `gh` adapter; `gh` owns authentication |
| Jira/Linear | Registration guidance only; no bundled credentials |
