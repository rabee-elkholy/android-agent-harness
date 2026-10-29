---
description: Run live agent-driven phone E2E on the installed build; persisted journeys are optional.
---

# Phone E2E verification

## Default: live session (choice "Run phone E2E")

When the developer selects **Run phone E2E** at sign-off, or asks for phone E2E
after install, run it immediately on the installed build. **Never revise the plan,
never rerun preflight, tests, reviewers or assemble for it.**

1. `python .agents/harness.py e2e start --task-id <id>` binds the phone from the
   current install/launch evidence and lists scenarios (plan phone checks,
   walkthrough, surface recipes). On Antigravity it returns the Device Hub pill;
   show it once so the developer can watch the phone live.
2. Add scenarios you derive from the changed code: `e2e add --title "..."`
   (happy path, back navigation, invalid/empty input, re-entry, process restart).
3. For every scenario: `e2e observe` (add `--screenshot` and view the PNG when
   visuals matter), act (`e2e tap --text|--resource-id|--desc|--x --y`,
   `e2e type --value "..."`, `e2e key --name BACK|ENTER|DEL|TAB`,
   `e2e swipe --direction up|down|left|right`, `e2e wait --seconds N|--until-text T`,
   `e2e restart`), observe again, then
   `e2e step --scenario S# --status PASS|FAIL|BLOCKED|SKIPPED --observed "..."`.
4. Human-only steps (Google/Facebook sign-in, OTP, payment, Wi-Fi off, account
   state, Arabic text entry, a physical action):
   `e2e need-developer --scenario S# --ask "<exact action>"`, ask with
   `ask_question` in the same turn (`Done - continue` / `Skip this scenario` /
   `Stop E2E`), then `e2e resume --scenario S#` and retry. `ENV_BLOCKED` (locked
   screen, disconnected phone) is handled the same way: ask, then retry once.
5. `e2e finish` writes an advisory report. Show a compact table (failures first)
   and ask for sign-off; record it with `device signoff --source conversation`
   quoting the report hash. A FAIL scenario is reported as FAIL; resume the task
   to fix it. Sensitive approval stays human-owned.

No uninstall, data clear, permission grant via adb, downgrade, system setting
change or purchase is ever performed by the session.

## Optional: persisted replayable journeys

Only when the developer explicitly wants a reusable journey contract for future
runs:

1. Read the approved plan and routed next action. Keep the same task, spending
   limits, counters, application work and evidence. Prepare is not PASS or final
   sensitive approval. Resume VERIFYING/BLOCKED before approved source edits.
2. Identify the actual app/module/variant, device policy and safe prerequisites.
   Use Graph/Task Context for source discovery. Define observable UI assertions
   and real resource IDs, exact text or content descriptions. Never invent
   selectors, coordinates or unsupported Android tooling. If the UI exposes no
   selectors, explain the limitation and obtain approval for any needed app change.
3. Draft a JSON verification contract in chat. Reuse a project-owned definition
   file when one exists. Do not create an out-of-scope configuration file before
   approval: revision also accepts inline JSON. The contract contains schema_version 1, criteria
   (id, expected, method, required) and executable journeys. A journey contains
   schema_version 1, id, version, purpose, criteria, module, variant,
   application_id, prerequisites, effects and steps. For example:

   ```json
   {
     "schema_version": 1,
     "criteria": [{"id": "screen", "expected": "Continue opens the next screen", "method": "journey", "required": true}],
     "journeys": [{
       "schema_version": 1, "id": "screen-flow", "version": 1,
       "purpose": "Verify one navigation transition", "criteria": ["screen"],
       "module": ":app", "variant": "Debug", "application_id": "com.example.app",
       "prerequisites": "App is on the first screen with safe test data",
       "effects": ["ui_interaction"],
       "steps": [
         {"action": "tap", "selector": {"content_desc": "Continue"}, "timeout": 5},
         {"action": "assert_present", "selector": {"text": "Next screen"}, "timeout": 5}
       ]
     }]
   }
   ```

   Replace every example identity/selector with discovered app values. Supported
   actions are tap, back, input, wait_present, assert_present and assert_absent.
   Each selector has exactly one resource_id, content_desc or exact text. Input
   uses a local secret_env reference, never a literal credential. The runner
   supports the primary Android user, at most 40 steps and 120 seconds, and needs
   at least one observable assertion. Validate journey files with
   `python .agents/harness.py journey validate --file <journey-json> --json`.
4. Embed the contract when drafting, or revise the existing task with
   `python .agents/harness.py task revise --task-id <id> --verification-contract <path-to-file.json>`.
   Write the JSON with your file tool first (any folder; Windows PowerShell strips
   double quotes from inline JSON). A reusable new file can be saved later if it is in approved
   scope. A changed plan hash needs its own approval and, where applicable, an
   explicit review-limit decision; the task's consumed calls/rounds never reset.
   When only the contract or phone checks change and the code is untouched, the
   approved revision reuses the frozen verification run: prepare-verification keeps
   preflight, unit tests, reviews, build and install, and routes straight to the
   journeys. Never rerun those steps manually.
   Present the changed effects/criteria for explicit approval through the normal
   revision flow. Do not edit internal plan or evidence files. A partial journey
   retains manual walkthrough sign-off. Add device_validation
   `manual_or_automatic` only when all selected journeys cover the complete
   walkthrough with observable assertions, one app/module/variant and the combined
   bounds above. Required human-only criteria cannot use this replacement mode.
5. Follow all routed preflight, unit, independent review, assemble and install/start
   prerequisites for the current snapshot. Phone E2E does not waive any of them.
   After successful installation, a complete approved walkthrough offers manual
   PASS/FAIL or **Run Automatically**. Use the developer's actual selected response
   with `device validate-automatically --task-id <id> --serial <installed-serial>
   --source conversation --proof-reference "<answer>"`. Partial approved journeys
   use `journey run --task-id <id> --id <journey-id> --serial <installed-serial> --json`
   and the normal criterion binding/manual sign-off path.
6. Report the actual assertions and result. Unit tests, independent reviews,
   successful startup or a UI dump alone are not phone E2E PASS. Failures remain
   failures; explain environment limitations and offer manual validation when
   appropriate. Never retry until green, grant permissions, clear data, uninstall,
   downgrade, purchase or authorize account writes implicitly. Sensitive final
   approval remains human-owned even after automatic PASS.
