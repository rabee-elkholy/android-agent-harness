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
