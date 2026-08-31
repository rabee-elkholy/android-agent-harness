# Threat Model — Android Agent Harness

Scope: threats against the harness itself and the Android checkout it governs.
Attackers: a compromised or misbehaving AI agent, a malicious prompt payload,
a malicious repository file, or a poisoned upstream dependency. Local humans
with filesystem write access are out of scope (they own the machine).

Version note: mitigation pointers below reference kit v0.12.0 code. Deny-class
mappings to deterministic test names live in `SECURITY.md`.

| Threat | Attack vector | Mitigation layer | Where enforced |
|---|---|---|---|
| 1. Prompt injection via repo instructions | Malicious `AGENTS.md`, `CLAUDE.md`, `harness-rules.md`, skill files, or MCP instructions steer the agent into unsafe actions | Command safety is decided by the deterministic engine from the command text, never by prompt prose: no prompt can whitelist git mutations, emulator tooling, `pm clear`, or device-bound adb without `-d`/`-s`. Adapters are written only for selected tools with a managed marker and pruned on re-install. A turn-start reminder re-asserts the canonical rules. `harness-rules.md` is declared the single source of truth (`trigger: always_on`) and the doctor fails un-replaced `{{...}}` template placeholders | `agents/scripts/pre_tool_safety.py` (decision engine); `agents/scripts/install_tool_adapters.py` (managed markers, pruning); `agents/scripts/pre_invocation_reminder.py`; `agents/scripts/harness_doctor.py` dimension 5 |
| 2. Tampering with `.agents/` config | Modified `hooks.json`, subagent prompts, or engine scripts weaken enforcement | Subagent prompts must match shipped templates verbatim (fingerprint + body). Doctor dimension 3 validates all 8 fingerprints. `ensure_hook_selftest.py` re-runs the full selftest whenever any harness file changes and injects an assemble-blocking failure notice on regression. Doctor dimension 2 checks `hooks.json` presence | `agents/scripts/_hook_state.py` (`prompts_match`); `agents/scripts/ensure_hook_selftest.py`; `harness_doctor.py` dimensions 2/3 |
| 3. Symlink / path-traversal via review package | `HARNESS_REVIEW_PACKAGE` points outside the repo (URL-encoded `..`, backslash traversal, symlink) to exfiltrate arbitrary files through reviewers | `resolve()` + repo/temp containment check on every package path; deny on escape | `pre_tool_safety.py` (`require_review_package`); tests `security_review_pkg_url_encoded_traversal`, `security_review_pkg_dotdot_backslash_traversal`, `security_review_pkg_symlink_escape` |
| 4. Secret exfiltration (logcat / env / MCP wiring) | Agent reads logs/env or poisoned MCP wiring copies tokens | Zoho credentials stay in user-level files; the installer refuses to write any JSON containing secret keys and aborts if written configs would contain actual token values. Doctor dimension 11 fails checkouts containing `<provider>.json` secret files. The audit log stores only a 12-hex command digest, never raw commands. Reviewers are instructed (and selftested) to flag `Log.*` leakage of PII/tokens in code | `agents/scripts/install_zoho_mcp.py`; `agents/mcp/zoho_sprints/_config.py`; `harness_doctor.py` dimension 11; `pre_tool_safety.py` (`write_audit`); `security-reviewer-agent.json` |
| 5. MCP tool poisoning | Malicious or compromised MCP server (upstream Jira/Linear, or a forged Zoho server) induces harmful tool calls | Only the kit-owned Zoho server ships in-repo; Jira/Linear are developer-registered upstream servers with user-level credentials. All tracker mutations are gated behind explicit trigger phrases and offline handoff/status validation that fails closed on unknown statuses. MCP config written by the kit never contains secret keys | `agents/scripts/pm_policy.py`; `agents/pm/mcp_registration.*.md`; `install_zoho_mcp.py` |
| 6. adb data-wipe / privilege escalation bypass | `pm clear` laundering via `adb shell cmd package clear <pkg>`; bare `adb root` / `adb remount` / `adb backup` / `adb reboot` without a device binding | `cmd package clear|uninstall` denied with the same rationale as `pm clear`. Privilege/data-exfil verbs (`root`, `remount`, `backup`, `reboot`, `sync`) require `-d`/`-s <serial>` like every other device-bound verb | `policy_vocab.py` (`DEVICE_BOUND_ADB`); `pre_tool_safety.py` (pm-op scan); tests `security_adb_root_bare_denied`, `security_adb_backup_bare_denied`, `security_adb_cmd_package_clear_denied` |
| 7. Floating kit provisioning | Installer pulls `main` instead of a pinned release | CLI provisions only detached `v<version>` tags, asserts `agents/VERSION` after checkout, refuses named branches, fails closed offline | `harness_cli.py` (`ensure_kit`, `refresh_kit`); tests `cli pinned provision`, `cli pin mismatch fails closed` |

## Accepted residual risks

- **Copilot preToolUse hook timeout is fail-open** on the Copilot side: the bridge keeps its engine call bounded and registers a tight `timeoutSec`, but a hung shell that exceeds the timeout is not denied by Copilot. The Antigravity and Claude Code paths fail closed. (`copilot_pre_tool_safety.py` header documents this.)
- **Antigravity terminal sandbox is disabled** (`agents/settings.json` `terminalSandbox: false`, eager auto-exec): safety rests entirely on the deny engine plus the grants deny-list; both are covered by deterministic tests, and the grants example is kept in parity with the vocabulary by the selftest.
- **`review_package.py` embeds untracked file contents** in the review package (gitignored state dir, read by subagents only). An untracked secret file would be included; developers should keep secrets out of the tree (doctor `.gitignore` audit reinforces this).
- **Zoho `save_config` 0600 permissions are POSIX-only**; on Windows the user config falls back to default ACLs. Keep `~/.android-harness/zoho_sprints.json` inside the user profile.
- **`adb shell run-as`** (with `-d`/`-s`) remains allowed as a legitimate debugging aid used by the QA diagnostics agent; it can read app-private files and is accepted.
- **`harness-rules.md` content is existence-checked, not hash-checked** by the doctor. Its behavioral authority is prompt-level; the machine-enforced denials do not depend on it.
- **Prompt-level tools** (Cursor, Codex, Windsurf, Cline, Roo, Qwen, Amazon Q, Continue, Junie, Kilo, Goose, and AGENTS.md readers) follow rules by instruction only; machine enforcement is limited to Antigravity hooks, Claude Code PreToolUse, the Copilot preToolUse hook, and the universal pre-commit git gate. See `docs/compatibility-matrix.md`.

## Out of scope

Physical access, OS-level compromise, git history forgery by repo owners, and
denial-of-service of the developer's own machine.

## Reporting

Report vulnerabilities per `SECURITY.md` — private security advisories only,
never a public issue.
