# Adaptive delivery automation

Automation begins only after an explicitly approved plan is consumed. Analysis and planning remain read-only.

The deterministic change classifier selects relevant knowledge skills and the central review policy selects tests, reviewers, assemble, and device verification. Never dispatch a fixed reviewer roster or run every expensive gate by habit.

Every gate writes immutable evidence bound to the current delivery snapshot, change set, run id, producer, and harness version. A later file or ignored-input change makes the run stale. The final verifier is read-only.

Reviewer responses must refer to the complete immutable review package. Use only the roles listed in the active policy. Test changes add test-quality review; critical security, authentication, billing, cryptography, or sensitive-data changes select the complete specialist set.

Build outputs form one APK artifact set. Split APK members are hashed and installed together. Device absence is an environment block; forced installation is emergency-unverified and cannot approve delivery.
