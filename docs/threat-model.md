# Threat model

Scope: the v1 harness, its local state, and the Android checkout it governs.
A compromised agent, malicious repository text, malformed tool output, and
concurrent local processes are in scope. A human or OS administrator with
unrestricted filesystem access is outside the trust boundary.

| Threat | Fail-closed control | Residual limitation |
|---|---|---|
| Agent starts implementation without approval | Single-use plan hash/nonce plus mutation hook/rules | Conversation approval is not cryptographic on rule-only hosts |
| Plan, branch, base, skill, policy, or final tree drifts | Repository/worktree identity, deterministic policy recomputation, content hashes, and final snapshot comparison | A machine owner can edit both code and state |
| Reviewer result is fabricated, partial, or stale | Exact policy roster, package/snapshot/change binding, structured reports, append-only run evidence, three-round cap | Reviewer semantic quality still depends on the selected model |
| Gate result is forged or reused | Exact producer/schema/version/run/snapshot/change binding | This is local evidence, not remote attestation |
| Harness files are weakened | File-tool protection, release checksums, ownership hashes, doctor/selftests | Arbitrary local code execution is not an OS sandbox |
| Path traversal or symlink escape | Resolved repository containment and bounded evidence paths | Existing filesystem permissions remain authoritative |
| Secret leakage | Key/value redaction, secret-path review redaction, hashed command audit, user-level credentials | Source code itself may contain a secret and must be remediated |
| Git history or external state changes implicitly | Git mutation deny classes; plan-scoped Zoho tool writes | Hosts that do not expose tool interception remain rule-enforced |
| Tracker retry duplicates a write | Stable operation IDs and a crash-safe pending/completed ledger | A timeout leaves an unknown outcome requiring inspection |
| Device data is overwritten | Explicit target, artifact-set binding, uninstall/clear/downgrade deny, confirmation | A developer can deliberately run ADB outside the harness |
| Split/stale APK is launched | `output-metadata.json` resolution and assemble/install/launch artifact-set chain | OEM/runtime behavior still requires device evidence |
| Concurrent evidence writers corrupt state | Exclusive PID/process-marker locks, atomic replace, append-only artifact names | Network filesystems may have weaker locking semantics |
| Environment failure is misreported as code failure or PASS | `ENV`/exit-30 classification and read-only verifier | Tool output classifiers cannot understand every vendor failure |
| Update damages user configuration | Ownership manifest, checksum validation, staging, backup, conflict refusal, rollback, dry-run uninstall | Power loss at an OS filesystem boundary may require backup recovery |

## Explicit non-claims

- `HARD_ENFORCED` is not an OS sandbox and does not make an agent-generated
  conversation token human-authentic.
- The classifier is deterministic pattern analysis, not complete Kotlin
  semantic analysis.
- Configuring a CI matrix does not prove those jobs passed.
- Emergency device actions never produce normal delivery approval.
- The harness does not protect against the repository owner intentionally
  modifying Git history or local evidence.

Report vulnerabilities through the private process in `SECURITY.md`.
