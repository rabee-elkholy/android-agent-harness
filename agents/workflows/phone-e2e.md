---
description: Prepare and execute approved phone E2E journeys without substituting JVM tests.
---

# Phone E2E verification

During UI/navigation planning, offer bounded automatic phone verification and
explain which checks still require human judgment. Use the existing task approval;
do not add a setup-wizard question or silently change device policy.

When the developer explicitly requests phone E2E, or selects **Prepare phone E2E**:

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
   `python .agents/harness.py task revise --task-id <id> --verification-contract '<inline-json>'`.
   A repository-relative JSON file is also accepted. Use the host shell's proper
   argument quoting. A reusable new file can be saved later if it is in approved
   scope. A changed plan hash needs its own approval and, where applicable, an
   explicit review-limit decision; the task's consumed calls/rounds never reset.
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
