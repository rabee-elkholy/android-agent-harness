---
name: android-security-billing
description: Android security, authentication, sensitive-data, cryptography, and Play Billing guidance.
version: 1.0.0
kernel-major: 1
---

# Android Security, Authentication, and Billing

Load this skill only when the deterministic classifier selects a security-sensitive surface.

## Required approach

- Preserve the approved product behavior and treat authentication, purchase, and cryptographic contracts as public boundaries.
- Never log credentials, purchase tokens, authorization headers, personal data, or unredacted provider responses.
- Keep secrets outside the repository and outside generated evidence.
- Validate exported components, intent inputs, URI permissions, and pending-intent mutability.
- Do not weaken TLS, certificate validation, Play Billing acknowledgement, purchase verification, or token expiry behavior to make a test pass.
- Test success, cancellation, retry, duplicate delivery, stale session, and provider failure behavior where the project exposes a meaningful seam.
- Never complete a real charge during automated validation.

This skill cannot waive plan approval, deterministic gates, sensitive delivery approval, or any kernel safety rule.
