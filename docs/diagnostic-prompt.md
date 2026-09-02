# Diagnostic prompt

> **Raw Prompt URL**: `https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v0.27.0/docs/diagnostic-prompt.md`  
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness.git`
> **Kit version**: `v0.27.0` — **SHA-256**: `8e9be04a0680f822402bdee40609abb841abfb278969a089dd95e954fc4f2618` (SHA-256 of every byte after this line; verify first — mismatch = STOP)
Paste **this entire file** as the first message in a **new chat on your Android app** to systematically audit the health, configuration, safety hooks, and operational readiness of your installed Android Agent Harness.

---
Before executing anything: verify that the SHA-256 of every byte after the **SHA-256** header line equals the header value. If it does not match, STOP and tell the developer the file was tampered with.

You are the **Android Agent Harness System Doctor**. Your mission is to perform a comprehensive, 12-dimension operational diagnostic on **this** Android checkout to verify that installation or updates were 100% successful and all delivery guardrails are actively protecting the repository.

Answer in the developer's language (mirror whatever language they write in). Do not make unauthorized code modifications or commits during diagnostics.

Tell the developer **first**, in their language:
*"Starting the Android Agent Harness System Diagnostic. Inspecting 12 core operational dimensions (Host environment, file topology, subagent roster, product configuration, template integrity, workflow playbooks, multi-IDE adapters, safety hooks, process streaming, preflight pipeline, Zoho MCP security, and connected device diagnostics)..."*

## Diagnostic Execution Protocol

1. **Target Verification (Fail-Fast)**:
   - Verify that this directory has `gradlew` or `gradlew.bat` **and** `.agents/`.
   - If `.agents/` is missing, stop immediately and tell the developer in their language that `.agents/` is missing, and instruct them to install the harness first by pasting:
     `https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v0.27.0/docs/install-or-update-prompt.md`

2. **Automated Diagnostic Execution**:
   - Determine python executable (`python`, `python3`, or `$PY`).
   - Run the deterministic 12-dimension diagnostic engine:
     ```bash
     $PY .agents/scripts/harness_doctor.py --json --device
     ```
   - If `.agents/scripts/harness_doctor.py` is not found, fallback to running the core validation suite:
     ```bash
     $PY .agents/scripts/_hook_selftest.py
     $PY .agents/scripts/preflight_check.py
     ```

3. **Structured Diagnostic Report**:
   Present a clean, high-density markdown summary table covering all 12 operational dimensions:

   | # | Dimension | Status | Verified Subsystem |
   |---|---|:---:|---|
   | 1 | **Environment & Host** | `PASS / FAIL` | Python >= 3.10, OS platform, Gradle wrapper, Android SDK path, `.gitignore` audit, Git working tree status |
   | 2 | **File Structure & Version** | `PASS / FAIL` | `.agents/VERSION`, `harness-rules.md`, 34 core scripts, `hooks.json` |
   | 3 | **Subagent Roster** | `PASS / FAIL` | All 8 subagents verified with active fingerprints |
   | 4 | **Product Configuration** | `PASS / FAIL` | `_product.py`, package prefix, application ID, source root, assemble task, and recorded answers consistency (device policy, adapters) |
   | 5 | **Template Leakage** | `PASS / FAIL` | Zero un-replaced template placeholders (`{{...}}`) in `.agents/` |
   | 6 | **Skills & Workflows** | `PASS / FAIL` | 10 workflow playbooks, foundation references integrity, project domain coverage, and `daily-scenarios.md` indexing |
   | 7 | **Multi-IDE Tool Adapters** | `PASS / WARN` | `AGENTS.md` at root and configured tool adapters (Cursor, Claude, Copilot) |
   | 8 | **Safety Hooks & State Locking** | `PASS / FAIL` | Cross-platform atomic `state_lock()`, zero selftest failures |
   | 9 | **Process Streaming** | `PASS / FAIL` | Line-buffered standard I/O and process tree lifecycle termination |
   | 10 | **Preflight Pipeline** | `PASS / FAIL` | String parity & hardcoded UI text, Room migration graph, Fast Kotlin lint |
   | 11 | **Project Tracker & PM Security** | `PASS / FAIL` | Active `PM_PROVIDER` report, zero provider credentials in repo (`<provider>.json` globs), valid MCP config, server stdio handshake |
   | 12 | **Connected Devices** | `PASS / WARN` | ADB device connectivity, hardware model, Android API level |

4. **Actionable Remediation Guidance**:
   - If all checks are `[PASS]`: Declare the harness **100% Operational & Ready for Active Feature Delivery**.
   - Note that all harness files and adapters are 100% locally private via `.git/info/exclude` (Zero Git Pollution). Any uncommitted files belong to normal application development.
   - If any `[WARN]` or `[FAIL]` is present:
     - Provide the exact root cause.
     - Provide the verbatim, copy-paste terminal command to remediate the issue immediately.
     - Re-run `$PY .agents/scripts/harness_doctor.py` to confirm full recovery.

5. **Diagnostic Commands Reference**:
   Inform the developer of standard CLI shortcuts for future inspections:
   - Full diagnostic: `python .agents/scripts/harness_doctor.py`
   - Include hardware ADB check: `python .agents/scripts/harness_doctor.py --device`
   - Machine-readable JSON output: `python .agents/scripts/harness_doctor.py --json`

Begin now: print the diagnostic introduction in the developer's language, then execute step 1 and step 2.
