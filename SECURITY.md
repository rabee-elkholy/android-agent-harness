# Security Policy

## Supported Versions

We actively maintain and provide security patches for the following versions of **Android Agent Harness**:

| Version | Supported |
| ------- | --------- |
| 0.10.x  | Yes       |
| 0.9.x   | Yes       |
| 0.8.x   | Yes       |
| 0.7.x   | Yes       |
| 0.6.x   | Yes       |
| 0.5.x   | Yes       |
| 0.4.x   | Yes       |
| 0.3.x   | Yes       |
| 0.2.x   | Yes       |
| < 0.2.0 | No        |

---

## Threat Model & Mitigations

Each attack class below maps to the exact selftest assertion that proves the
mitigation. The adversarial suite lives in `agents/scripts/_security_selftest.py`
(run standalone, from `_hook_selftest.py`, and in CI) — every case is
deterministic and performs zero network I/O.

| Attack class | Mitigation | Proving test |
| ------------ | ---------- | ------------ |
| Git mutation hidden behind a chained inspection command (`git status && git push`) | Every shell-chained segment is scanned independently | `security_git_chained_push` |
| Git mutation obfuscated by whitespace (`git     reset`) | Whitespace-collapsed command normalization before scanning | `security_git_spaced_reset` |
| Git mutation hidden behind config options (`git -c k=v commit`, `--git-dir`) | Option tokenizer skips `-c/-C/--git-dir/--work-tree` values before verb lookup | `security_git_config_wrapped_commit` |
| Homoglyph / extension laundering (`gıt.exe push`, full-path `git.exe`) | NFKC + confusables fold map applied before the mutation regex | `security_git_homoglyph_exe_push`, `security_git_fullpath_exe_push` |
| Encoded payload piped into a shell (`base64 -d \| sh`, `sh -c`) | Shell-indirection patterns denied outright | `security_git_base64_wrapped_reset` |
| Review-package path traversal (URL-encoded `%2e%2e`, `..\..\`, symlinked dir) | `resolve()` + repo/temp containment check on every HARNESS_REVIEW_PACKAGE | `security_review_pkg_url_encoded_traversal`, `security_review_pkg_dotdot_backslash_traversal`, `security_review_pkg_symlink_escape` |
| Oversized hook stdin (memory exhaustion / payload smuggling) | 5 MB payload cap, fail-closed denial | `security_oversized_stdin_payload` |
| Malformed bridge input (Claude Code PreToolUse fuzz) | Bridge always exits 0 with a JSON deny; garbage input denies | `security_cc_bridge_garbage_stdin`, `security_cc_bridge_git_push_denied` |
| Malformed bridge input (GitHub Copilot preToolUse fuzz) | Deterministic allow/deny for camelCase + VS Code snake_case payloads; garbage denies | `security_copilot_camelcase_push_denied`, `security_copilot_snakecase_push_denied`, `security_copilot_garbage_stdin_denied` |
| Forged review verdicts (PASS tokens without EVIDENCE footer, wrong pkg hash) | Evidence-backed barrier: footer `pkg=` must equal the dispatched package hash | `security_forged_evidence_footer_blocked`, `security_forged_evidence_wrong_pkg_blocked` |
| Secret leakage through MCP wiring (token keys/values in server responses or configs) | Secret-key detection, token-value scan, and refuse-to-write guards in the Zoho install path | `security_zoho_helper_detects_secret_keys`, `security_zoho_helper_refuses_secret_write`, `security_zoho_helper_scans_token_values`, `security_zoho_install_leaves_no_token_values` |
| Floating/unpinned kit provisioning (drift to `main`, tag/version mismatch) | Pin-to-tag clone/refresh with post-checkout VERSION assert, fail-closed remediation | `cli pinned provision`, `cli refresh re-pins drifted checkout`, `cli pin mismatch fails closed` (in `_hook_selftest.py`) |

---

## Reporting a Vulnerability

If you discover a potential security vulnerability (such as a safety hook bypass, unintended command execution, or credential exposure in MCP integrations):

1. **Do NOT open a public GitHub issue.**
2. Report the vulnerability privately via **[GitHub Private Security Advisories](https://github.com/rabee-elkholy/android-harness-kit/security/advisories/new)** or by contacting the maintainer directly at `rabeeaelkholy123@gmail.com`.
3. Include:
   - Description of the vulnerability.
   - Step-by-step reproduction instructions or proof-of-concept.
   - Affected harness version and environment (OS, Python version, AI tool).

We take security issues seriously and will respond promptly within 48 hours to validate and resolve any verified concerns.