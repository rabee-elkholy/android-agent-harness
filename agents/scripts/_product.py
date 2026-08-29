"""Product identity for this checkout. Setup overwrites these from Gradle/manifests."""
from __future__ import annotations

PRODUCT_NAME = "this Android app"
APPLICATION_ID = "com.example.app"
LAUNCHER = "com.example.app/.MainActivity"
PACKAGE_PREFIX = "com.example"
ASSEMBLE_TASK = ":app:assembleDebug"
UNIT_TEST_TASK = ":app:testDebugUnitTest"
APK_RELATIVE = "app/build/outputs/apk/debug/app-debug.apk"
# Classic Android source root. KMP is often composeApp/src/androidMain — setup rewrites this.
ANDROID_SRC = ("app", "src", "main")
# Build variants (flavors). Setup wizard I.19 fills these when productFlavors exist.
ACTIVE_FLAVOR = ""  # "" = default variant (no flavors). e.g. "staging"
ASSEMBLE_TASKS = {}  # flavor -> task, e.g. {"staging": ":app:assembleStagingDebug"}
APK_RELATIVES = {}  # flavor -> debug APK path, e.g. {"staging": "app/build/outputs/apk/staging/debug/app-staging-debug.apk"}
# Language & Tracker settings (configured during setup)
CHAT_LANGUAGE = "mirror"  # "mirror" (Mirror developer language in chat: Arabic with Arabic, English with English)
TRACKER_LANGUAGE = "en_titles_ar_comments"  # "en_titles_ar_comments", "all_en", "all_ar" (Zoho / Jira / Linear / GitHub)
ZOHO_LANGUAGE = TRACKER_LANGUAGE  # Alias for backward compatibility
ALLOW_EMULATOR = True  # True (both physical and emulator allowed), False (physical device only)
# Project tracker (setup wizard I.20). Absent/empty = zoho_sprints (historical default).
# Options: zoho_sprints | github_projects | jira_mcp | linear_mcp | none
PM_PROVIDER = "zoho_sprints"
# Adaptive architecture & stack properties (auto-configured by setup wizard)
DI_FRAMEWORK = "hilt"  # "hilt" | "koin" | "dagger" | "manual" | "none"
UI_FRAMEWORK = "compose"  # "compose" | "xml_views" | "hybrid"
SUPPORTED_LOCALES = ["en", "ar"]  # List of discovered locale tags e.g. ["en", "ar", "fr"]
PROJECT_STRUCTURE = "single_module"  # "single_module" | "multi_module" | "kmp"


