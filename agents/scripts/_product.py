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
# Language & Zoho settings (configured during setup)
CHAT_LANGUAGE = "en"  # "en" (Strict English), "mirror" (Mirror developer input), "ar" (Arabic)
ZOHO_LANGUAGE = "en_titles_ar_comments"  # "en_titles_ar_comments", "all_en", "all_ar"
ALLOW_EMULATOR = True  # True (both physical and emulator allowed), False (physical device only)

