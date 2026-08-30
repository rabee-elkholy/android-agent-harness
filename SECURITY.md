# Security Policy

## Supported Versions

We actively maintain and provide security patches for the latest minor release line of the **Android Agent Harness**.

| Version Line | Supported |
| :--- | :--- |
| **v0.14.x** | Yes |
| < v0.14.0 | No |

---

## Security Architecture & Invariants

The Android Agent Harness is designed with strict OS-level containment and cryptographic security invariants:

1. **Zero Secret Leakage**:
   - Provider tokens, API keys, and credentials are kept strictly out of Git repositories via `.git/info/exclude`.
   - Logcat interceptors actively sanitize sensitive authentication tokens, authorization headers, and PII before output.
2. **Deterministic PreToolUse Hook Containment**:
   - Python safety hooks intercept and reject destructive commands (`git reset --hard`, `git push --force`, `pm clear`, bare destructive ADB commands) before they reach the OS shell.
3. **Cryptographic Delivery Gate**:
   - Subagent reviews produce SHA-256 evidence footers linked to the immutable review package diff. No forged or synthetic verdicts are accepted.
4. **Local Git Privacy (Zero Team Pollution)**:
   - All harness configurations, adapters, transient states, and pre-commit hooks are stored locally in `.git/info/exclude`, leaving the shared team repository 100% clean.

---

## Reporting a Vulnerability

If you discover a potential security vulnerability within the Android Agent Harness:

1. **Do not create a public GitHub issue.**
2. Please disclose the vulnerability privately via **[GitHub Private Vulnerability Reporting](https://github.com/rabee-elkholy/android-harness-kit/security/advisories/new)**.
3. Include detailed steps to reproduce the vulnerability, including platform information, Python version, and relevant logs.

We take security seriously and will investigate and patch verified vulnerabilities promptly.