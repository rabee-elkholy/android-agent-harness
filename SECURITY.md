# Security policy

## Supported versions

| Version line | Supported |
|---|---|
| **v1.3.x** | Yes |
| v1.2.x | Yes |
| v1.1.x | No, upgrade to v1.3.x |
| v1.0.x | No, upgrade to v1.3.x |
| < v1.0.0 | No |

## Security boundary

Android Agent Harness is a local development control layer, not an OS sandbox
or remote-attestation system. Its guarantees are deliberately bounded:

- an approved, hash-bound plan and single-use run identity are required before
  project mutation;
- host hooks deny covered unplanned file writes, raw Gradle/ADB, Git mutations,
  destructive device actions, shell laundering, live probes, and unplanned
  tracker writes;
- deterministic policy is recomputed during final verification, so a stored
  policy cannot silently drop gates or reviewers;
- gate/review evidence is append-only and bound to one snapshot, change set,
  run, producer, schema, and harness version;
- review packages redact secret-shaped paths and evidence recursively redacts
  secret-shaped keys and values;
- release payload checksums, ownership hashes, staged replacement, backup, and
  rollback protect install/update/uninstall;
- Zoho writes require approved plan scope plus a stable operation ID; unknown
  outcomes block blind retry and terminal states remain developer-owned.

Conversational approval is reported as `RULE_ENFORCED`. `HARD_ENFORCED` is used
only for mutation classes intercepted by an actual host-native boundary and
never claims cryptographic human identity or universal bypass resistance.

See [the threat model](docs/threat-model.md) for residual risks and non-claims.

## Reporting a vulnerability

Do not open a public issue. Use
[GitHub Private Vulnerability Reporting](https://github.com/rabee-elkholy/android-agent-harness/security/advisories/new)
and include reproduction steps, operating system, Python version, host adapter,
and sanitized logs.

## Incident reporting and recovery

Public incident bodies, titles and prefilled links export only allowlisted metadata
(version, known host/OS/category/state, a fingerprint and a healed flag). Raw
messages, command arguments, stack traces and arbitrary extra fields stay local,
including when an older incident is submitted. Local redaction is best-effort;
review local logs before sharing them. The metadata export does not certify local
logs as free of personal information.

State recovery rejects snapshots with mismatched task identity, unsupported schema,
invalid plan hash or unbound active approval. Invalid snapshots cannot overwrite a
corrupt plan. PM status/transition IDs without verified meaning require explicit
close authority; an accompanying caller-supplied name is insufficient. Existing
Bug/Issue descriptions are protected even when the replacement is empty or null.
