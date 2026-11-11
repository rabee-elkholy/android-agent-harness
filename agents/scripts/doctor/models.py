"""Diagnostic data structures and core asset manifests for Harness Doctor."""
from __future__ import annotations

from dataclasses import dataclass

CORE_SUBAGENTS = {
    "bug-test-reviewer-agent": "HARNESS_BUG_FINGERPRINT=quality-first-bug-review-v3",
    "security-perf-reviewer-agent": "HARNESS_SECURITY_FINGERPRINT=quality-first-security-review-v3",
    "arch-regression-reviewer-agent": "HARNESS_REGRESSION_FINGERPRINT=quality-first-regression-impact-v3",
    "qa-diagnostics-agent": "HARNESS_QA_FINGERPRINT=deep-device-diagnostics-v3",
    "android-ui-expert-agent": "HARNESS_UI_FINGERPRINT=comprehensive-android-ui-expert-v4",
    "spec-compliance-agent": "HARNESS_SPEC_COMPLIANCE_FINGERPRINT=quality-first-spec-compliance-v2",
}

CORE_SCRIPTS = (
    "_enforcement.py",
    "_adb_core.py",
    "_environment.py",
    "_graph_core.py",
    "_hook_selftest.py",
    "_live_process.py",
    "_modules.py",
    "_product.py",
    "_repo_files.py",
    "_variants.py",
    "_vnext_common.py",
    "artifact_set.py",
    "change_classifier.py",
    "delegation_policy.py",
    "delivery_manifest.py",
    "evidence_store.py",
    "final_verifier.py",
    "lifecycle.py",
    "mutation_guard.py",
    "plan_authority.py",
    "review_policy.py",
    "skill_router.py",
    "workflow.py",
    "capture_screen.py",
    "cc_pre_tool_safety.py",
    "check_kit_update.py",
    "check_strings.py",
    "copilot_pre_tool_safety.py",
    "ensure_hook_selftest.py",
    "fast_kt_lint.py",
    "gradle_error_parser.py",
    "harness_doctor.py",
    "install_or_update.py",
    "install_tool_adapters.py",
    "logcat_doctor.py",
    "new_feature_scaffold.py",
    "perf_guard.py",
    "pm_github.py",
    "pm_policy.py",
    "pre_invocation_reminder.py",
    "pre_tool_safety.py",
    "preflight_check.py",
    "project_graph.py",
    "record_review.py",
    "review_package.py",
    "room_guard.py",
    "run_device.py",
    "run_gradle_task.py",
    "run_tests_gate.py",
    "setup_wizard.py",
)

CORE_WORKFLOWS = (
    "deliver.md",
    "debug.md",
    "new-feature.md",
    "commit-msg.md",
    "crash-triage.md",
    "perf-audit.md",
    "preflight.md",
    "check-strings.md",
    "test-quality-audit.md",
    "pm-tracker.md",
)

CORE_REFERENCES = (
    "architecture-guidelines.md",
    "ui-layout-and-theming.md",
    "database-and-persistence.md",
    "performance-and-optimization.md",
    "test-quality-guidelines.md",
    "automated-skills.md",
    "daily-scenarios.md",
)

KNOWN_DOMAINS = {
    "Networking & API": {
        "signatures": ("retrofit", "retrofit2", "io.ktor", "ktor-client", "okhttp3", "com.apollographql"),
        "expected_prefixes": ("networking-", "api-"),
        "sample_file": "networking-api-contracts.md",
    },
    "Payments & Billing": {
        "signatures": ("com.android.billingclient", "billing-ktx", "com.stripe", "revenuecat", "fawry"),
        "expected_prefixes": ("payment-", "billing-"),
        "sample_file": "payment-gateways-architecture.md",
    },
    "Ads & Monetization": {
        "signatures": ("play-services-ads", "com.google.android.gms.ads", "applovin", "unity-ads", "user-messaging-platform"),
        "expected_prefixes": ("ad-", "ads-"),
        "sample_file": "ad-mediation-privacy.md",
    },
    "Location & Maps": {
        "signatures": ("play-services-location", "play-services-maps", "com.mapbox", "ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION"),
        "expected_prefixes": ("location-", "maps-"),
        "sample_file": "location-maps-services.md",
    },
    "Hardware & Sensors": {
        "signatures": ("SensorEventListener", "SensorManager", "androidx.camera", "camera-camera2", "android.bluetooth"),
        "expected_prefixes": ("hardware-", "sensor-", "fitness-", "camera-", "bluetooth-"),
        "sample_file": "hardware-bluetooth-camera.md",
    },
    "Audio & Media": {
        "signatures": ("androidx.media3", "exoplayer", "SoundPool", "MediaPlayer"),
        "expected_prefixes": ("audio-", "media-"),
        "sample_file": "audio-media-playback.md",
    },
}


@dataclass
class CheckResult:
    category: str
    name: str
    status: str  # "PASS", "WARN", "FAIL"
    message: str
    details: list[str] | None = None
