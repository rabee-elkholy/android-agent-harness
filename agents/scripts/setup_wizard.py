"""Record setup answers so install does not depend on a short chat modal.

Interactive (developer terminal):

    python agents/scripts/setup_wizard.py --repo /path/to/android --lang ar

Agent-assisted (do not shorten the printed prompts):

    python agents/scripts/setup_wizard.py questions --repo /path/to/android --lang ar
    python agents/scripts/setup_wizard.py write --repo /path/to/android --answers-json answers.json
    python agents/scripts/setup_wizard.py flags --repo /path/to/android

Writes <repo>/.harness-setup/answers.json and SETUP_ANSWERS.md.
Does not copy .agents or port the engine.
"""
# TODO(audit/2026-02): consider splitting this ~72KB module (discovery, i18n
# tables, questions, normalize/write CLI) — deferred, see ROADMAP.md.
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCHEMA = 1
try:
    from pm_policy import WIZARD_PROVIDER_IDS as PM_PROVIDER_IDS  # noqa: E402
except ImportError:  # pragma: no cover - kit layout always ships pm_policy
    PM_PROVIDER_IDS = ("zoho_sprints", "github_projects", "jira_mcp", "linear_mcp", "none")
DEFAULT_PM_PROVIDER = "zoho_sprints"
SKIP_DIRS = {
    ".git",
    "build",
    ".gradle",
    ".idea",
    ".agents",
    ".harness-backup",
    ".harness-setup",
    "node_modules",
    "__pycache__",
}
TOOL_IDS = (
    "cursor",
    "claude",
    "copilot",
    "gemini",
    "codex",
    "qwen",
    "windsurf",
    "cline",
    "roo",
    "amazonq",
    "continue",
    "junie",
    "kilo",
    "goose",
)
TOOL_LABELS = {
    "en": {
        "cursor": "Cursor",
        "claude": "Claude Code",
        "copilot": "GitHub Copilot",
        "gemini": "Gemini / Antigravity",
        "codex": "Codex",
        "qwen": "Qwen Code",
        "windsurf": "Windsurf",
        "cline": "Cline",
        "roo": "Roo",
        "amazonq": "Amazon Q",
        "continue": "Continue",
        "junie": "Junie",
        "kilo": "Kilo",
        "goose": "Goose",
        "all": "All of them",
    },
    "ar": {
        "cursor": "Cursor",
        "claude": "Claude Code",
        "copilot": "GitHub Copilot",
        "gemini": "Gemini / Antigravity",
        "codex": "Codex",
        "qwen": "Qwen Code",
        "windsurf": "Windsurf",
        "cline": "Cline",
        "roo": "Roo",
        "amazonq": "Amazon Q",
        "continue": "Continue",
        "junie": "Junie",
        "kilo": "Kilo",
        "goose": "Goose",
        "all": "كلهم",
    },
}

T = {
    "en": {
        "i0": (
            "Setup will replace the AI helper files in this project. A backup lets you restore "
            "them if something goes wrong. Without a backup, the old files cannot be restored."
        ),
        "i0_yes": "Back up and start (Recommended)",
        "i0_skip": "Start without a backup",
        "i0_no": "Stop setup",
        "i1": (
            "What name should the helper use for this app? I found “{name}”. "
            "Reviews and AGENTS.md will show that name."
        ),
        "i1_use": "Use “{name}” (Recommended)",
        "i1_other": "Other name (I will type it)",
        "i2": "Which Python command should the scripts use? On Windows this is usually python.",
        "i2_stop": "Stop — install Python 3.10+",
        "i3": (
            "Who should create git commits? If you are not sure, keep commits in your own hands "
            "(you commit from the IDE)."
        ),
        "i3_never": "I commit myself (Recommended)",
        "i3_may": "The agent may commit when I ask in chat",
        "i4": (
            "Will you test this app on a real phone, an emulator (AVD), or both? "
            "Pick both unless you never use an emulator. Physical only blocks emulator install and logcat."
        ),
        "i4_skip": "Phone and emulator both allowed (Recommended)",
        "i4_allow": "Phone and emulator both allowed (Recommended)",
        "i4_phys": "Physical phone only — no emulator",
        "i5": "Which Gradle module is the Android app that builds the APK?",
        "i5_other": "Other module (I will type it)",
        "i6": "Which screen opens when the app launches?",
        "i6_other": "Other activity (I will type it)",
        "i6b": (
            "The live runner checks that this debug APK exists after assemble. The kit example is "
            "app-debug.apk; many KMP apps are composeApp-debug.apk. A wrong path looks like a failed build."
        ),
        "i6b_use": "Use discovered path: {path}",
        "i6b_glob": "Glob **/outputs/apk/debug/*.apk",
        "i6b_other": "Other path (I will type it)",
        "i7": (
            "Reviewers only flag what they can cite. If we keep the kit’s MVI/Hilt/Room/ads rules, "
            "they will false-fail a Koin/KMP/BaseViewModel app. Using the stack I discovered makes "
            "reviews match how you write code."
        ),
        "i7_use": "Use discovered stack: {stack} (Recommended)",
        "i7_keep": "Keep the kit’s MVI/Hilt/Room rules",
        "i8": (
            "String checks compare keys across locale folders. If you only have values/, we skip "
            "AR/EN parity so preflight does not fail on a missing values-ar. If you have two folders, "
            "we keep the pair so translations do not drift."
        ),
        "i8_use": "Use discovered folders: {folders}",
        "i8_other": "Other locales (I will type them)",
        "i9": (
            "The new-screen generator still has example-product paths until we retarget it. Disable "
            "it so the agent cannot create junk packages. Retarget it if you want faster new screens "
            "in this tree. Disable is safer when the layout is not app/src/main/java."
        ),
        "i9_dis": "Disable it now (Recommended)",
        "i9_ret": "Retarget it to this project now",
        "i10": (
            "Before the helper installs the app on the phone or emulator, should it ask you first? "
            "Asking avoids installing on the wrong device. Skipping is faster if you trust the serial."
        ),
        "i10_conf": "Ask me first (Recommended)",
        "i10_allow": "Install without asking",
        "i15": (
            "After the helper finishes code and review, should it run unit tests "
            "(checks logic without opening the app)? Pick no if this project has no tests and you will not add them."
        ),
        "i15_yes": "Yes, run unit tests (Recommended)",
        "i15_no": "No, skip unit tests",
        "i11": (
            "When someone clones this app from GitHub, should they get the same AI helper rules, "
            "or should those files stay only on your PC? If you work alone, keep them on your PC. "
            "This setup will not commit either way."
        ),
        "i11_gi": "Only on my PC — not on GitHub (Recommended)",
        "i11_later": "In the project so teammates get them after a clone",
        "i12": (
            "~/.gemini/config.json is for the whole PC, not this repo. Another app on this machine "
            "may already use it. Merging the script allowlist only leaves that global file alone except "
            "for safe grants. A global rule is only for when this is the only Antigravity project on the PC."
        ),
        "i12_merge": "Merge script allowlist only (Recommended)",
        "i12_global": "This is the only Antigravity project — write a global rule",
        "i13": (
            "Selftest + preflight prove the harness scripts. A full :assembleDebug also proves your "
            "SDK/wrapper and shows the 10s heartbeat, but it costs compile time. Tests only is enough "
            "to finish setup."
        ),
        "i13_tests": "Tests only (selftest + preflight) (Recommended)",
        "i13_asm": "Yes, run :assembleDebug at the end",
        "i14": (
            "Which programs do you open this project in? Select every one you use. "
            "If you use Cursor, you must select Cursor so its rules get written."
        ),
        "i16": (
            "Does this project use Zoho Sprints? The helper can list and update sprint items. "
            "Credentials stay in a file on this PC. Setup will not copy tokens into the repo "
            "and will not ask you to paste them. Skip if you do not use Zoho."
        ),
        "i16_enable_found": "Enable Zoho Sprints — reuse the credentials already on this PC (Recommended)",
        "i16_enable": "Enable Zoho Sprints — I will add credentials after setup",
        "i16_skip": "Skip — no Zoho on this project",
        "i16_skip_rec": "Skip — no Zoho (Recommended)",
        "i17": (
            "What is your preferred language for engineering chat, implementation plans, subagent reviews, and git commits?"
        ),
        "i17_en": "Strict English everywhere (Recommended for Android engineering)",
        "i17_mirror": "Mirror developer language (English if addressed in English, Arabic if addressed in Arabic)",
        "i17_ar": "Arabic (عربي)",
        "i18": (
            "What is your preferred language for Zoho Sprints task descriptions and comments?"
        ),
        "i18_en_titles_ar_comments": "English task titles + Arabic comments and descriptions (Recommended)",
        "i18_all_en": "All English (Titles, Descriptions, and Comments in English)",
        "i18_all_ar": "All Arabic (عربي بالكامل)",
        "i20": (
            "Which project tracker should govern task ingest and updates? "
            "Zoho Sprints is the built-in default. GitHub Projects uses the gh CLI. "
            "Jira and Linear use their official upstream MCP servers (a registration "
            "guide is printed after install). Mutations stay locked behind an explicit "
            "trigger phrase for every tracker."
        ),
        "i20_zoho_sprints": "Zoho Sprints — built-in MCP server (Recommended, current default)",
        "i20_github_projects": "GitHub Projects & Issues — via the gh CLI",
        "i20_jira_mcp": "Jira — official upstream MCP server (registration guide)",
        "i20_linear_mcp": "Linear — official upstream MCP server (registration guide)",
        "i20_none": "None — local-only delivery, no tracker",
        "i21": (
            "Should the helper install a staged-changes quality gate before every git commit? "
            "It adds .githooks/pre-commit (string parity, Room migrations, Kotlin lint) and runs in "
            "under 5 seconds. Choose no only if you already run your own git hooks."
        ),
        "i21_yes": "Yes — install the pre-commit quality gate (Recommended)",
        "i21_no": "No — I manage my own git hooks",
        "i19": (
            "This project defines Gradle product flavors. Which flavor do you test daily? "
            "Install/launch/logcat will target that variant automatically. "
            "Pick the default variant if you do not use flavors daily."
        ),
        "i19_default": "Default variant only — no daily flavor (Recommended if unsure)",
        "auto_blurb": (
            "From this project I will use (no extra questions): Python {py}, "
            "module {module}, launcher {launcher}, APK {apk}, stack {stack}, locales {locales}. "
            "If Gemini config exists on this PC, only merge script grants. "
            "Zoho Sprints is optional and never copies tokens. "
            "Finish with harness tests, not a full app build. Answer only the questions below."
        ),
        "model_warning": (
            "WARNING: Run this setup in a strong model chat, not a fast/cheap one. "
            "Install is a structural port (package, module, APK, architecture, leftover grep, selftest). "
            "A weak model skips steps, shortens questions, and leaves a broken helper. "
            "Stay until Total test failures: 0. If this chat is a small model, stop and start a new one."
        ),
        "type_value": "Type the value:",
        "pick": "Enter number",
        "pick_multi": "Enter numbers (comma-separated)",
        "defaults_note": (
            "Previous answers found in .harness-setup/answers.json. "
            "Each question shows (current) — press Enter to keep it, type a number to change."
        ),
        "invalid": "Invalid choice.",
        "stopped": "Stopped. No answers written.",
        "wrote": "Wrote {path}",
        "b_platform": "What is the target platform architecture for this project?",
        "b_platform_kmp": "Kotlin Multiplatform (KMP: Android + iOS / Desktop / Web) (Recommended)",
        "b_platform_native": "Android Native (Kotlin + AndroidX)",
        "b_arch": "Which Architecture Pattern will this project follow?",
        "b_arch_mvi": "MVI with Unidirectional Data Flow (State + Action + Channel Events & BaseViewModel) (Recommended)",
        "b_arch_mvvm": "MVVM with StateFlow / SharedFlow & ViewModel",
        "b_arch_clean": "Clean Architecture + MVI (Data -> Domain/UseCases -> Presentation/MVI)",
        "b_di": "Which Dependency Injection (DI) framework will you use?",
        "b_di_koin": "Koin (koin-core / koin-compose / koin-android) (Recommended for KMP & Kotlin)",
        "b_di_hilt": "Dagger Hilt (@HiltViewModel, @Inject, @AndroidEntryPoint) (Recommended for Native Android)",
        "b_di_manual": "Manual DI / Constructor Injection",
        "b_nav": "Which Navigation framework will you use?",
        "b_nav_voyager": "Voyager (cafe.adriel.voyager with Screen model) (Recommended for Compose/KMP)",
        "b_nav_comp": "Jetpack Compose Navigation (androidx.navigation.compose)",
        "b_nav_decompose": "Decompose (arkivanov/decompose)",
        "b_ui": "Which UI framework will you use?",
        "b_ui_compose": "Jetpack Compose / Compose Multiplatform with Material 3 (Recommended)",
        "b_ui_xml": "XML Layouts + ViewBinding",
        "b_db": "Which local database / storage engine will this project use?",
        "b_db_room": "Room Database (androidx.room with KSP & explicit migrations) (Recommended)",
        "b_db_sql": "SQLDelight (app.cash.sqldelight for KMP)",
        "b_db_datastore": "Jetpack DataStore Preferences (Key-Value)",
        "b_db_none": "No database needed initially",
        "b_net": "Which networking client will this project use?",
        "b_net_ktor": "Ktor Client (io.ktor:ktor-client with kotlinx.serialization) (Recommended for KMP)",
        "b_net_retrofit": "Retrofit + OkHttp (Recommended for Native Android)",
        "b_net_none": "No remote API initially (Local-only app)",
        "b_locales": "Which localization and language support do you need?",
        "b_locales_dual": "Bilingual Arabic (RTL) + English (LTR) with dual-locale previews (Recommended)",
        "b_locales_en": "English only",
        "b_locales_ar": "Arabic only",
        "no_python": "No working Python 3.10+ on PATH.",
        "need_repo": "Need --repo pointing at an Android checkout with gradlew.",
    },
    "ar": {
        "i0": (
            "هركّب ملفات مساعد التطوير في المشروع ده. النسخة الاحتياطية تخليك ترجع لو حصل غلط. "
            "من غير نسخة مش هتقدر ترجع الملفات القديمة."
        ),
        "i0_yes": "نسخة احتياطية وابدأ (مفضّل)",
        "i0_skip": "ابدأ من غير نسخة",
        "i0_no": "وقف التثبيت",
        "i1": (
            "اسم التطبيق اللي هيظهر للمساعد: لقيت «{name}». نستخدمه ولا تكتب اسم تاني؟"
        ),
        "i1_use": "استخدم «{name}» (مفضّل)",
        "i1_other": "اسم تاني (هكتبه)",
        "i2": "أي أمر Python نستخدمه؟ على ويندوز غالباً python مش python3.",
        "i2_stop": "قف — ثبّت Python 3.10+",
        "i3": (
            "مين يعمل git commit؟ لو مش متأكد، خلّي الكوميت بإيدك (من Cursor أو أي IDE)."
        ),
        "i3_never": "أنا اللي بعمل الكوميت (مفضّل)",
        "i3_may": "المساعد يعمل كوميت لما أطلب في الشات",
        "i4": (
            "هتختبر التطبيق على موبايل حقيقي، ولا محاكي (AVD)، ولا الاتنين؟ "
            "لو بتستخدم المحاكي حتى أحيانًا اختار الاتنين. موبايل بس بيمنع التثبيت واللوج من المحاكي."
        ),
        "i4_skip": "الاتنين: موبايل ومحاكي (مفضّل)",
        "i4_allow": "الاتنين: موبايل ومحاكي (مفضّل)",
        "i4_phys": "موبايل حقيقي فقط — من غير محاكي",
        "i5": "أنهي جزء من المشروع هو التطبيق اللي بيتبني (ملف الـ APK)؟",
        "i5_other": "موديول تاني (هكتبه)",
        "i6": "أنهي شاشة بتفتح أول ما التطبيق يشتغل؟",
        "i6_other": "Activity تاني (هكتبه)",
        "i6b": (
            "الـ runner بيتأكد إن ملف الـ debug APK موجود بعد الـ assemble. مثال الكيت app-debug.apk؛ "
            "مشاريع KMP غالباً composeApp-debug.apk. المسار الغلط باين كفشل بيلد."
        ),
        "i6b_use": "استخدم المسار: {path}",
        "i6b_glob": "Glob **/outputs/apk/debug/*.apk",
        "i6b_other": "مسار تاني (هكتبه)",
        "i7": (
            "المراجعين ما يعلّموش إلا على قاعدة مكتوبة. لو سيبنا قواعد MVI/Hilt/Room/الإعلانات، "
            "هيفشلوا أبلكيشن Koin/KMP/BaseViewModel بالغلط. الستاك اللي اكتشفته يخلي المراجعة مطابقة لشغلك."
        ),
        "i7_use": "استخدم الستاك المكتشف: {stack} (مفضّل)",
        "i7_keep": "خلّي قواعد MVI/Hilt/Room بتاعة الكيت",
        "i8": (
            "فحص الاسترنجات بيقارن المفاتيح بين مجلدات اللغات. لو عندك values/ بس، نتخطى مقارنة AR/EN "
            "عشان الـ preflight مايفشلش. لو فيه مجلدين، نخليهم عشان الترجمة ما تتشتتش."
        ),
        "i8_use": "المجلدات المكتشفة: {folders}",
        "i8_other": "لغات تانية (هكتبها)",
        "i9": (
            "مولّد الشاشات لسه ماشي على مسارات المثال. عطّله عشان الوكيل ما يعملش باكيدجز غلط. "
            "أو وجّهه للمشروع ده لو عايز شاشات جديدة أسرع. التعطيل أأمن لو المشروع مش app/src/main/java."
        ),
        "i9_dis": "عطّله دلوقتي (مفضّل)",
        "i9_ret": "وجّهه للمشروع دلوقتي",
        "i10": (
            "قبل ما المساعد يركّب التطبيق على الموبايل أو المحاكي، يسألك ولا يركّب على طول؟ "
            "السؤال يمنع تركيب على جهاز غلط."
        ),
        "i10_conf": "اسألني الأول (مفضّل)",
        "i10_allow": "ركّب من غير سؤال",
        "i15": (
            "بعد ما المساعد يخلّص الكود والمراجعة، يشغّل يونيت تيست ولا نعدّي من غيرها؟ "
            "اليونيت تيست بيفحص المنطق من غير ما يفتح التطبيق. لو المشروع مالوش تيستات ومش هتضيف، اختار لا."
        ),
        "i15_yes": "نعم، شغّل يونيت تيست (مفضّل)",
        "i15_no": "لا، من غير يونيت تيست",
        "i11": (
            "لما حد يعمل clone للمشروع من GitHub، ياخد نفس قواعد المساعد، ولا الملفات تفضل عندك "
            "على الجهاز ده بس؟ لو بتشتغل لوحدك: على جهازك بس. التثبيت الحالي مش هيعمل كوميت."
        ),
        "i11_gi": "عندي على الجهاز بس — مش على GitHub (مفضّل)",
        "i11_later": "في المشروع عشان زميلي ياخدها بعد الـ clone",
        "i12": (
            "ملف ~/.gemini/config.json للجهاز كله مش للريبو. تطبيق تاني على الجهاز ممكن يكون بيستخدمه. "
            "دمج الـ allowlist بس أأمن. القاعدة العامة بس لو ده مشروع Antigravity الوحيد على الجهاز."
        ),
        "i12_merge": "ادمج allowlist السكربتات فقط (مفضّل)",
        "i12_global": "ده مشروع Antigravity الوحيد — اكتب قاعدة عامة",
        "i13": (
            "Selftest + preflight يثبتوا سكربتات الـ harness. :assembleDebug كمان يثبت الـ SDK "
            "ويظهر الـ heartbeat، بس بياخد وقت كومبايل. الاختبارات كفاية لختام التثبيت."
        ),
        "i13_tests": "اختبارات فقط (selftest + preflight) (مفضّل)",
        "i13_asm": "نعم، شغّل :assembleDebug في الآخر",
        "i14": (
            "بتفتح المشروع ده في أنهي برامج؟ علّم على كل اللي بتستخدمه. "
            "لو بتستخدم Cursor لازم تختاره عشان ملفاته تتكتب."
        ),
        "i16": (
            "المشروع ده بيستخدم Zoho Sprints؟ المساعد يقدر يعرض ويحدّث عناصر الـ sprint. "
            "التوكين يفضل في ملف على الجهاز. التثبيت مش هينسخ التوكين للريبو "
            "ومش هيطلبك تلصقه. لو مش بتستخدم Zoho اختار تخطي."
        ),
        "i16_enable_found": "فعّل Zoho Sprints — استخدم بيانات الدخول الموجودة على الجهاز (مفضّل)",
        "i16_enable": "فعّل Zoho Sprints — هضيف بيانات الدخول بعد التثبيت",
        "i16_skip": "تخطي — المشروع من غير Zoho",
        "i16_skip_rec": "تخطي — من غير Zoho (مفضّل)",
        "i17": (
            "ما هي لغة المحادثة والخطط الهندسية وتقارير المراجعين والكوميت المفضلة؟"
        ),
        "i17_en": "إنجليزي هندسي فقط في كل شيء (مفضّل لتطوير أندرويد ومنع تداخل النصوص)",
        "i17_mirror": "مطابقة لغة المطور (إنجليزي لو كلمته إنجليزي، عربي لو كلمته عربي)",
        "i17_ar": "عربي بالكامل",
        "i18": (
            "ما هي اللغة المفضلة لتحديثات ووصف وتعليقات مهام Zoho Sprints؟"
        ),
        "i18_en_titles_ar_comments": "عناوين المهام بالإنجليزي والوصف/التعليقات بالعربي (مفضّل)",
        "i18_all_en": "إنجليزي بالكامل (العناوين والوصف والتعليقات بالإنجليزي)",
        "i18_all_ar": "عربي بالكامل",
        "i20": (
            "أنهي نظام مهام (Tracker) يحكم استلام المهام وتحديثها؟ "
            "Zoho Sprints هو الافتراضي المدمج. GitHub Projects بيشتغل عبر gh CLI. "
            "Jira و Linear عندهم خوادم MCP رسمية (دليل التسجيل هيطبع بعد التثبيت). "
            "التحديث محجوز لعبارة صريحة في الشات مع كل نظام."
        ),
        "i20_zoho_sprints": "Zoho Sprints — خادم MCP مدمج (مفضّل، الافتراضي الحالي)",
        "i20_github_projects": "GitHub Projects و Issues — عبر gh CLI",
        "i20_jira_mcp": "Jira — خادم MCP رسمي (دليل تسجيل)",
        "i20_linear_mcp": "Linear — خادم MCP رسمي (دليل تسجيل)",
        "i20_none": "بدون نظام مهام — تسليم محلي فقط",
        "i21": (
            "المساعد يركّب بوابة جودة قبل كل git commit؟ "
            "بتضيف .githooks/pre-commit (تطابق النصوص، ترحيلات Room، فحص Kotlin) وشغلها أقل من 5 ثواني. "
            "اختار لا بس لو عندك hooks جاهزة بتديرها بنفسك."
        ),
        "i21_yes": "نعم — ركّب بوابة الجودة قبل الكوميت (مفضّل)",
        "i21_no": "لا — هدير hooks الجيت بنفسي",
        "i19": (
            "المشروع فيه Product Flavors. أنهي نسخة بتختبر عليها يومياً؟ "
            "التثبيت والتشغيل واللوج هيشتغلوا على النسخة دي. "
            "اختار الافتراضي لو مش بتستخدم Flavors في الشغل اليومي."
        ),
        "i19_default": "الافتراضي فقط — بدون Flavor يومي (مفضّل لو مش متأكد)",
        "auto_blurb": (
            "من المشروع هستخدم من غير أسئلة زيادة: Python {py}، "
            "الموديول {module}، الشاشة الأولى {launcher}، ملف APK {apk}، طريقة الكتابة {stack}، "
            "اللغات {locales}. لو فيه إعداد Gemini على الجهاز هعدّل سماح السكربتات "
            "بس. Zoho Sprints اختياري ومش بينسخ التوكين. "
            "في الآخر اختبارات المساعد مش بيلد كامل للتطبيق. الأسئلة اللي تحت هي اللي محتاج إجابة."
        ),
        "model_warning": (
            "تنبيه: التثبيت لازم على شات بموديل قوي، مش الموديل السريع/الرخيص. "
            "الشغل نقل هيكلي (باكدج، موديول، APK، طريقة الكتابة، فحص البقايا، selftest). "
            "الموديل الضعيف بيختصر الأسئلة وبيسيب مساعد مكسور. "
            "كمّل لحد ما يطبع Total test failures: 0. لو الشات ده موديل صغير، وقف وافتح شات جديد بموديل أقوى."
        ),
        "type_value": "اكتب القيمة:",
        "pick": "اكتب الرقم",
        "pick_multi": "اكتب الأرقام مفصولة بفاصلة",
        "defaults_note": (
            "لقينا إجابات سابقة في .harness-setup/answers.json. "
            "كل سؤال هيظهر جنبه (current) — دوس Enter عشان تفضلّه، أو اكتب رقم لتغييره."
        ),
        "invalid": "اختيار غلط.",
        "stopped": "اتوقف. مفيش إجابات اتكتبت.",
        "wrote": "اتكتب {path}",
        "b_platform": "ما هي منصة الاستهداف الأساسية لهذا المشروع؟",
        "b_platform_kmp": "Kotlin Multiplatform (KMP: أندرويد + iOS / ديسكتوب / ويب) (مفضّل)",
        "b_platform_native": "أندرويد أصيل (Android Native: Kotlin + AndroidX)",
        "b_arch": "ما هو نمط المعمارية (Architecture Pattern) الذي سيتبعه المشروع؟",
        "b_arch_mvi": "MVI مع تدفق بيانات أحادي (State + Action + Channel Events مع BaseViewModel) (مفضّل)",
        "b_arch_mvvm": "MVVM مع StateFlow / SharedFlow و ViewModel",
        "b_arch_clean": "Clean Architecture + MVI (طبقات Data ➔ Domain/UseCases ➔ Presentation/MVI)",
        "b_di": "ما هي مكتبة حقن الاعتماديات (Dependency Injection) المستخدمة؟",
        "b_di_koin": "Koin (koin-core / koin-compose / koin-android) (مفضّل لـ KMP وكوتلن)",
        "b_di_hilt": "Dagger Hilt (@HiltViewModel, @Inject, @AndroidEntryPoint) (مفضّل لـ Native Android)",
        "b_di_manual": "حقن يدوي (Manual DI / Constructor Injection)",
        "b_nav": "ما هي مكتبة التنقل (Navigation) المستخدمة؟",
        "b_nav_voyager": "Voyager (cafe.adriel.voyager مع Screen Model) (مفضّل لـ Compose و KMP)",
        "b_nav_comp": "Jetpack Compose Navigation Component الرسمي",
        "b_nav_decompose": "Decompose (arkivanov/decompose)",
        "b_ui": "ما هو إطار واجهة المستخدم (UI Framework)؟",
        "b_ui_compose": "Jetpack Compose / Compose Multiplatform مع Material 3 (مفضّل)",
        "b_ui_xml": "XML Views مع ViewBinding كلاسيكي",
        "b_db": "ما هي قاعدة البيانات أو وحدة التخزين المحلية المستخدمة؟",
        "b_db_room": "Room Database (androidx.room مع ترحيلات Schema صريحة) (مفضّل)",
        "b_db_sql": "SQLDelight (app.cash.sqldelight لمشاريع KMP)",
        "b_db_datastore": "DataStore Preferences لتخزين الإعدادات",
        "b_db_none": "لا توجد قاعدة بيانات حالياً",
        "b_net": "ما هي مكتبة الاتصال بالإنترنت والـ API؟",
        "b_net_ktor": "Ktor Client (io.ktor مع kotlinx.serialization) (مفضّل لـ KMP)",
        "b_net_retrofit": "Retrofit + OkHttp (مفضّل لـ Native Android)",
        "b_net_none": "تطبيق محلي فقط بدون API حالياً",
        "b_locales": "ما هي اللغات المدعومة ومعايير الواجهة؟",
        "b_locales_dual": "ثنائي اللغة: عربي (RTL) + إنجليزي (LTR) مع Dual Previews (مفضّل)",
        "b_locales_en": "إنجليزي فقط",
        "b_locales_ar": "عربي فقط",
        "no_python": "مفيش Python 3.10+ شغال على PATH.",
        "need_repo": "محتاج --repo على مشروع أندرويد فيه gradlew.",
    },
}


def t(lang: str, key: str, **kwargs: str) -> str:
    table = T["ar" if lang == "ar" else "en"]
    return table[key].format(**kwargs)


def setup_dir(repo: Path) -> Path:
    return repo / ".harness-setup"


def answers_path(repo: Path) -> Path:
    return setup_dir(repo) / "answers.json"


def markdown_path(repo: Path) -> Path:
    return setup_dir(repo) / "SETUP_ANSWERS.md"


def skip_path(path: Path, repo: Path) -> bool:
    try:
        parts = set(path.relative_to(repo).parts)
    except ValueError:
        return True
    return bool(parts & SKIP_DIRS)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def python_ok(cmd: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [cmd, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    out = f"{proc.stdout or ''}{proc.stderr or ''}"
    if proc.returncode != 0:
        return False, out.strip()
    low = out.lower()
    if "microsoft store" in low or "windowsapps" in low:
        return False, out.strip()
    if "python 2." in low:
        return False, out.strip()
    return True, out.strip() or cmd


def discover_product(repo: Path) -> str:
    for name in ("settings.gradle.kts", "settings.gradle"):
        text = read_text(repo / name)
        m = re.search(r'rootProject\.name\s*=\s*["\']([^"\']+)["\']', text)
        if m:
            return m.group(1)
    return repo.name


def discover_pythons() -> list[str]:
    found: list[str] = []
    for cmd in ("python", "python3"):
        ok, _ver = python_ok(cmd)
        if ok and cmd not in found:
            found.append(cmd)
    return found


def gradle_files(repo: Path) -> list[Path]:
    out: list[Path] = []
    for pat in ("**/build.gradle.kts", "**/build.gradle"):
        for path in repo.glob(pat):
            if not skip_path(path, repo):
                out.append(path)
    return out


def discover_modules(repo: Path) -> list[str]:
    modules: list[str] = []
    for path in gradle_files(repo):
        text = read_text(path)
        if "applicationId" not in text and "androidApplication" not in text:
            if "com.android.application" not in text:
                continue
        if re.search(r"androidApplication.*apply\s+false", text) or re.search(
            r"com\.android\.application.*apply\s+false", text
        ):
            continue
        if "applicationId" not in text and "namespace" not in text:
            continue
        rel = path.parent.relative_to(repo).as_posix()
        if rel == ".":
            mod = ":app"
        else:
            mod = ":" + rel.replace("/", ":")
        if mod not in modules:
            modules.append(mod)
    return modules


def discover_application_ids(repo: Path) -> list[str]:
    ids: list[str] = []
    for path in gradle_files(repo):
        text = read_text(path)
        for m in re.finditer(r'applicationId(?:\s*=\s*|\s+)["\']([^"\']+)["\']', text):
            if m.group(1) not in ids:
                ids.append(m.group(1))
        for m in re.finditer(r'namespace(?:\s*=\s*|\s+)["\']([^"\']+)["\']', text):
            if m.group(1) not in ids:
                ids.append(m.group(1))
    return ids


def discover_launchers(repo: Path) -> list[str]:
    ids = discover_application_ids(repo)
    pkg = ids[0] if ids else ""
    found: list[str] = []
    for path in repo.glob("**/AndroidManifest.xml"):
        if skip_path(path, repo):
            continue
        text = read_text(path)
        if "android.intent.action.MAIN" not in text:
            continue
        if "android.intent.category.LAUNCHER" not in text:
            continue
        for m in re.finditer(r'android:name="(\.[^"]+)"', text):
            rel = m.group(1)
            if "Activity" not in rel and rel not in {".MainActivity", ".app.MainActivity"}:
                if "Activity" not in rel:
                    continue
            if pkg:
                comp = f"{pkg}/{rel}"
            else:
                comp = rel
            if comp not in found:
                found.append(comp)
        for m in re.finditer(r'android:name="([a-zA-Z0-9_.]+\.[A-Za-z][A-Za-z0-9_]*Activity)"', text):
            comp = m.group(1)
            if pkg and "/" not in comp:
                if comp.startswith(pkg):
                    rest = comp[len(pkg) :]
                    comp = f"{pkg}/{rest if rest.startswith('.') else '.' + rest.split('.')[-1]}"
            if comp not in found:
                found.append(comp)
    return found


def discover_apk_hint(repo: Path) -> str:
    modules = discover_modules(repo)
    if any("composeApp" in m for m in modules):
        return "composeApp/build/outputs/apk/debug/*.apk"
    if any(m == ":app" or m.endswith(":app") for m in modules):
        return "app/build/outputs/apk/debug/app-debug.apk"
    return "**/outputs/apk/debug/*.apk"


def discover_locales(repo: Path) -> list[str]:
    names: set[str] = set()
    for path in repo.glob("**/res/values*"):
        if skip_path(path, repo) or not path.is_dir():
            continue
        names.add(path.name)
    return sorted(names)


def discover_stack(repo: Path) -> str:
    chunks: list[str] = []
    for path in gradle_files(repo):
        chunks.append(read_text(path))
    for toml in repo.glob("**/libs.versions.toml"):
        if not skip_path(toml, repo):
            chunks.append(read_text(toml))
    n = 0
    for folder in ("composeApp", "app", "shared", "androidApp", "core", "presentation"):
        root = repo / folder
        if not root.is_dir():
            continue
        for path in root.rglob("*.kt"):
            if skip_path(path, repo):
                continue
            chunks.append(read_text(path))
            n += 1
            if n >= 120:
                break
        if n >= 120:
            break
    text = "\n".join(chunks)
    bits: list[str] = []
    if "org.koin" in text or "koin-android" in text or "startKoin" in text or "koin-compose" in text:
        bits.append("Koin")
    if "dagger.hilt" in text or "@HiltViewModel" in text or "hilt-android" in text:
        bits.append("Hilt")
    if "cafe.adriel.voyager" in text or "voyager-navigator" in text:
        bits.append("Voyager")
    if "MVIViewModel" in text:
        bits.append("MVIViewModel")
    if "BaseViewModel" in text:
        bits.append("BaseViewModel")
    if "androidx.room" in text or "room-runtime" in text:
        bits.append("Room")
    if any("composeApp" in m for m in discover_modules(repo)):
        bits.append("Compose Multiplatform")
    elif "androidx.compose" in text:
        bits.append("Jetpack Compose")
    return " + ".join(bits) if bits else "unknown (confirm in chat)"


def has_classic_app_src(repo: Path) -> bool:
    return (repo / "app" / "src" / "main" / "java").is_dir() or (
        repo / "app" / "src" / "main" / "kotlin"
    ).is_dir()


_FLAVOR_KEYWORDS = {"dimension", "missingdimensionstrategy", "isdefault", "targetsdk", "versionname"}


def _product_flavors_block(text: str) -> str:
    m = re.search(r"productFlavors\s*\{", text)
    if not m:
        return ""
    start = m.end() - 1
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def discover_flavors(repo: Path) -> list[str]:
    names: list[str] = []
    for path in gradle_files(repo):
        block = _product_flavors_block(read_text(path))
        if not block:
            continue
        for cm in re.finditer(r'create\s*\(\s*["\']([^"\']+)["\']', block):
            names.append(cm.group(1))
        for lm in re.finditer(r"(?m)^\s{2,}([a-z][a-zA-Z0-9_]*)\s*\{", block):
            if lm.group(1).lower() not in _FLAVOR_KEYWORDS:
                names.append(lm.group(1))
    seen: list[str] = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return seen


def _flavor_pascal(name: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^a-zA-Z0-9]", name) if part)


def gemini_exists() -> bool:
    return (Path.home() / ".gemini" / "config.json").is_file() or (
        Path.home() / ".gemini" / "config" / "config.json"
    ).is_file()


def zoho_config_present() -> bool:
    mcp = Path(__file__).resolve().parent.parent / "mcp" / "zoho_sprints"
    if str(mcp) not in sys.path:
        sys.path.insert(0, str(mcp))
    from _config import resolve_config_path  # noqa: E402

    return resolve_config_path() is not None


def count_source_files(repo: Path) -> int:
    count = 0
    for pat in ("**/*.kt", "**/*.java"):
        for p in repo.glob(pat):
            if not skip_path(p, repo):
                count += 1
                if count > 50:
                    return count
    return count


def discover(repo: Path) -> dict:
    modules = discover_modules(repo)
    pythons = discover_pythons()
    locales = discover_locales(repo)
    source_count = count_source_files(repo)
    return {
        "product": discover_product(repo),
        "pythons": pythons,
        "modules": modules,
        "launchers": discover_launchers(repo),
        "apk_hint": discover_apk_hint(repo),
        "locales": locales,
        "stack": discover_stack(repo),
        "classic_app_src": has_classic_app_src(repo),
        "gemini": gemini_exists(),
        "zoho_config": zoho_config_present(),
        "gradlew": (repo / "gradlew").is_file() or (repo / "gradlew.bat").is_file(),
        "source_count": source_count,
        "is_empty": source_count == 0,
        "flavors": discover_flavors(repo),
    }


def auto_from_facts(facts: dict) -> dict:
    pythons = facts.get("pythons") or []
    modules = facts.get("modules") or []
    launchers = facts.get("launchers") or []
    hint = facts.get("apk_hint") or ""
    if hint:
        apk_mode = "path"
        apk_path = hint
    else:
        apk_mode = "glob"
        apk_path = "**/outputs/apk/debug/*.apk"
    return {
        "product": facts.get("product") or "App",
        "py": pythons[0] if pythons else "",
        "module": modules[0] if modules else "",
        "launcher": launchers[0] if launchers else "",
        "apk": apk_mode,
        "apk_path": apk_path,
        "architecture": facts.get("stack") or "unknown",
        "architecture_mode": "discovered",
        "locales": ", ".join(facts.get("locales") or ["values"]),
        "device_policy": "allow",
        "scaffold": "disable",
        "install_confirm": "confirm",
        "agents_git": "gitignore",
        "gemini_config": "merge-allowlist" if facts.get("gemini") else "skip",
        "assemble_now": "tests-only",
        "unit_tests": "yes",
        "zoho_mcp": "enable" if facts.get("zoho_config") else "skip",
        "chat_language": "en",
        "zoho_language": "en_titles_ar_comments",
        "pm_provider": DEFAULT_PM_PROVIDER,
    }


def auto_blurb(facts: dict, lang: str) -> str:
    a = auto_from_facts(facts)
    return t(
        lang,
        "auto_blurb",
        product=a["product"] or "?",
        py=a["py"] or "?",
        module=a["module"] or "?",
        launcher=a["launcher"] or "?",
        apk=a["apk_path"],
        stack=a["architecture"],
        locales=a["locales"],
    )


def questions_payload(repo: Path, lang: str, facts: dict | None = None) -> list[dict]:
    d = facts if facts is not None else discover(repo)
    labels = TOOL_LABELS["ar" if lang == "ar" else "en"]
    qs = [
        {
            "id": "i0",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i0"),
            "options": [
                {"id": "yes", "label": t(lang, "i0_yes")},
                {"id": "skip", "label": t(lang, "i0_skip")},
                {"id": "no", "label": t(lang, "i0_no")},
            ],
        },
        {
            "id": "i1",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i1", name=d.get("product") or "App"),
            "options": [
                {"id": "discovered", "label": t(lang, "i1_use", name=d.get("product") or "App")},
                {"id": "other", "label": t(lang, "i1_other")},
            ],
        },
    ]
    pythons = d.get("pythons") or []
    if len(pythons) != 1:
        py_opts = [{"id": p, "label": p} for p in pythons]
        py_opts.append({"id": "stop", "label": t(lang, "i2_stop")})
        qs.append(
            {
                "id": "i2",
                "required": True,
                "allow_multiple": False,
                "prompt": t(lang, "i2"),
                "options": py_opts,
            }
        )
    qs.append(
        {
            "id": "i3",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i3"),
            "options": [
                {"id": "never", "label": t(lang, "i3_never")},
                {"id": "agent-may-commit", "label": t(lang, "i3_may")},
            ],
        }
    )
    qs.append(
        {
            "id": "i4",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i4"),
            "options": [
                {"id": "allow", "label": t(lang, "i4_allow")},
                {"id": "physical-only", "label": t(lang, "i4_phys")},
            ],
        }
    )
    qs.append(
        {
            "id": "i10",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i10"),
            "options": [
                {"id": "confirm", "label": t(lang, "i10_conf")},
                {"id": "allow", "label": t(lang, "i10_allow")},
            ],
        }
    )
    qs.append(
        {
            "id": "i15",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i15"),
            "options": [
                {"id": "yes", "label": t(lang, "i15_yes")},
                {"id": "no", "label": t(lang, "i15_no")},
            ],
        }
    )
    modules = d.get("modules") or []
    if len(modules) != 1:
        mod_opts = [{"id": m, "label": m} for m in modules]
        mod_opts.append({"id": "other", "label": t(lang, "i5_other")})
        qs.append(
            {
                "id": "i5",
                "required": True,
                "allow_multiple": False,
                "prompt": t(lang, "i5"),
                "options": mod_opts,
            }
        )
    launchers = d.get("launchers") or []
    if len(launchers) != 1:
        launch_opts = [{"id": x, "label": x} for x in launchers]
        launch_opts.append({"id": "other", "label": t(lang, "i6_other")})
        qs.append(
            {
                "id": "i6",
                "required": True,
                "allow_multiple": False,
                "prompt": t(lang, "i6"),
                "options": launch_opts,
            }
        )
    tool_opts = [{"id": tid, "label": labels[tid]} for tid in TOOL_IDS]
    tool_opts.append({"id": "all", "label": labels["all"]})
    qs.append(
        {
            "id": "i14",
            "required": True,
            "allow_multiple": True,
            "prompt": t(lang, "i14"),
            "options": tool_opts,
        }
    )
    found = bool(d.get("zoho_config"))
    qs.append(
        {
            "id": "i16",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i16"),
            "options": [
                {
                    "id": "enable",
                    "label": t(lang, "i16_enable_found" if found else "i16_enable"),
                },
                {
                    "id": "skip",
                    "label": t(lang, "i16_skip" if found else "i16_skip_rec"),
                },
            ],
        }
    )
    qs.append(
        {
            "id": "i17",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i17"),
            "options": [
                {"id": "en", "label": t(lang, "i17_en")},
                {"id": "mirror", "label": t(lang, "i17_mirror")},
                {"id": "ar", "label": t(lang, "i17_ar")},
            ],
        }
    )
    qs.append(
        {
            "id": "i18",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i18"),
            "options": [
                {
                    "id": "en_titles_ar_comments",
                    "label": t(lang, "i18_en_titles_ar_comments"),
                },
                {
                    "id": "all_en",
                    "label": t(lang, "i18_all_en"),
                },
                {
                    "id": "all_ar",
                    "label": t(lang, "i18_all_ar"),
                },
            ],
        }
    )
    qs.append(
        {
            "id": "i20",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i20"),
            "options": [{"id": pid, "label": t(lang, f"i20_{pid}")} for pid in PM_PROVIDER_IDS],
        }
    )
    qs.append(
        {
            "id": "i21",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i21"),
            "options": [
                {"id": "yes", "label": t(lang, "i21_yes")},
                {"id": "no", "label": t(lang, "i21_no")},
            ],
        }
    )
    flavors = d.get("flavors") or []
    if flavors:
        flavor_opts = [{"id": f, "label": f} for f in flavors]
        flavor_opts.append({"id": "default", "label": t(lang, "i19_default")})
        qs.append(
            {
                "id": "i19",
                "required": True,
                "allow_multiple": False,
                "prompt": t(lang, "i19"),
                "options": flavor_opts,
            }
        )
    is_greenfield = d.get("is_empty") or d.get("source_count", 0) < 4 or d.get("stack") in ("unknown", "unknown (confirm in chat)", "")
    if is_greenfield:
        qs.append(
            {
                "id": "b_platform",
                "required": True,
                "allow_multiple": False,
                "prompt": t(lang, "b_platform"),
                "options": [
                    {"id": "kmp", "label": t(lang, "b_platform_kmp")},
                    {"id": "native", "label": t(lang, "b_platform_native")},
                ],
            }
        )
        qs.append(
            {
                "id": "b_arch",
                "required": True,
                "allow_multiple": False,
                "prompt": t(lang, "b_arch"),
                "options": [
                    {"id": "mvi", "label": t(lang, "b_arch_mvi")},
                    {"id": "mvvm", "label": t(lang, "b_arch_mvvm")},
                    {"id": "clean", "label": t(lang, "b_arch_clean")},
                ],
            }
        )
        qs.append(
            {
                "id": "b_di",
                "required": True,
                "allow_multiple": False,
                "prompt": t(lang, "b_di"),
                "options": [
                    {"id": "koin", "label": t(lang, "b_di_koin")},
                    {"id": "hilt", "label": t(lang, "b_di_hilt")},
                    {"id": "manual", "label": t(lang, "b_di_manual")},
                ],
            }
        )
        qs.append(
            {
                "id": "b_nav",
                "required": True,
                "allow_multiple": False,
                "prompt": t(lang, "b_nav"),
                "options": [
                    {"id": "voyager", "label": t(lang, "b_nav_voyager")},
                    {"id": "comp", "label": t(lang, "b_nav_comp")},
                    {"id": "decompose", "label": t(lang, "b_nav_decompose")},
                ],
            }
        )
        qs.append(
            {
                "id": "b_ui",
                "required": True,
                "allow_multiple": False,
                "prompt": t(lang, "b_ui"),
                "options": [
                    {"id": "compose", "label": t(lang, "b_ui_compose")},
                    {"id": "xml", "label": t(lang, "b_ui_xml")},
                ],
            }
        )
        qs.append(
            {
                "id": "b_db",
                "required": True,
                "allow_multiple": False,
                "prompt": t(lang, "b_db"),
                "options": [
                    {"id": "room", "label": t(lang, "b_db_room")},
                    {"id": "sql", "label": t(lang, "b_db_sql")},
                    {"id": "datastore", "label": t(lang, "b_db_datastore")},
                    {"id": "none", "label": t(lang, "b_db_none")},
                ],
            }
        )
        qs.append(
            {
                "id": "b_net",
                "required": True,
                "allow_multiple": False,
                "prompt": t(lang, "b_net"),
                "options": [
                    {"id": "ktor", "label": t(lang, "b_net_ktor")},
                    {"id": "retrofit", "label": t(lang, "b_net_retrofit")},
                    {"id": "none", "label": t(lang, "b_net_none")},
                ],
            }
        )
        qs.append(
            {
                "id": "b_locales",
                "required": True,
                "allow_multiple": False,
                "prompt": t(lang, "b_locales"),
                "options": [
                    {"id": "dual", "label": t(lang, "b_locales_dual")},
                    {"id": "en", "label": t(lang, "b_locales_en")},
                    {"id": "ar", "label": t(lang, "b_locales_ar")},
                ],
            }
        )
    return qs


def default_for_question(q: dict, defaults: dict) -> list[str]:
    """Map previously recorded answers to this question's option ids (pre-fill).

    Returns [] when no stored value matches an option, so the question is
    asked fresh (required). Multi-select questions return the stored tool list
    as default selection.
    """
    qid = str(q.get("id") or "")
    if qid not in defaults:
        return []
    stored = defaults[qid]
    if stored is None:
        return []
    if q.get("allow_multiple") and isinstance(stored, list):
        option_ids = [opt["id"] for opt in q["options"]]
        picked = [opt for opt in stored if opt in option_ids]
        return picked if picked else []
    if any(opt["id"] == stored for opt in q["options"]):
        return [stored]
    return []


def prompt_choice(q: dict, lang: str, default: list[str] | None = None) -> list[str]:
    default = default or []
    default_indexes = []
    if default:
        for idx, opt in enumerate(q["options"]):
            if opt["id"] in default:
                default_indexes.append(idx)
    print()
    print(q["prompt"])
    print()
    for i, opt in enumerate(q["options"], start=1):
        marker = "  (current)" if (i - 1) in default_indexes else ""
        print(f"  {i}) {opt['label']}{marker}")
    hint = t(lang, "pick_multi" if q.get("allow_multiple") else "pick")
    if not q.get("required"):
        hint += " [Enter = 1]"
    if default_indexes:
        labels = ", ".join(str(idx + 1) for idx in default_indexes)
        hint += f" [Enter = {labels}]"
    while True:
        raw = input(f"{hint}: ").strip()
        if not raw and not q.get("required"):
            return [q["options"][0]["id"]]
        if not raw and default_indexes:
            return [q["options"][idx]["id"] for idx in default_indexes]
        if q.get("allow_multiple"):
            if raw.lower() in {"all", "كلهم"}:
                return ["all"]
            nums: list[int] = []
            ok = True
            for part in raw.replace(" ", "").split(","):
                if not part.isdigit():
                    ok = False
                    break
                n = int(part)
                if n < 1 or n > len(q["options"]):
                    ok = False
                    break
                nums.append(n)
            if ok and nums:
                return [q["options"][n - 1]["id"] for n in nums]
        elif raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(q["options"]):
                return [q["options"][n - 1]["id"]]
        print(t(lang, "invalid"))


def prompt_text(lang: str) -> str:
    return input(f"{t(lang, 'type_value')} ").strip()


def normalize(raw: dict, facts: dict) -> dict:
    if raw.get("i0") == "no":
        return {"schema": SCHEMA, "i0": False, "backup": False}
    auto = auto_from_facts(facts)
    do_backup = raw.get("i0") != "skip"
    py = raw.get("i2") or auto["py"]
    if py in (None, "", "stop"):
        raise SystemExit("Python command missing or stop selected.")
    module = raw.get("i5") or auto["module"]
    if module == "other":
        module = raw.get("i5_text") or ""
    if module and not module.startswith(":"):
        module = ":" + module
    if not module:
        raise SystemExit("No application module found; set i5.")
    launcher = raw.get("i6") or auto["launcher"]
    if launcher == "other":
        launcher = raw.get("i6_text") or ""
    if not launcher:
        raise SystemExit("No launcher activity found; set i6.")
    apk = raw.get("i6b")
    apk_path = auto["apk_path"]
    if apk is None:
        apk = auto["apk"]
    elif apk == "other":
        apk_path = raw.get("i6b_text") or apk_path
        apk = "path"
    elif apk == "discovered":
        apk = "path"
        apk_path = facts.get("apk_hint") or apk_path
    elif apk == "glob":
        apk_path = "**/outputs/apk/debug/*.apk"
    else:
        apk = "path"
    product = auto["product"]
    if raw.get("i1") == "other":
        product = raw.get("i1_text") or product
    locales = auto["locales"]
    if raw.get("i8") == "other":
        locales = raw.get("i8_text") or locales
    stack = auto["architecture"]
    arch_mode = "keep-kit" if raw.get("i7") == "keep-kit" else "discovered"
    bootstrap_details = {}
    if raw.get("b_arch") or raw.get("b_platform"):
        p_val = raw.get("b_platform", "kmp")
        a_val = raw.get("b_arch", "mvi")
        d_val = raw.get("b_di", "koin")
        n_val = raw.get("b_nav", "voyager")
        u_val = raw.get("b_ui", "compose")
        db_val = raw.get("b_db", "room")
        net_val = raw.get("b_net", "ktor")
        loc_val = raw.get("b_locales", "dual")

        plat_str = "KMP" if p_val == "kmp" else "Android Native"
        arch_str = "MVI (State + Action + Channel)" if a_val == "mvi" else ("MVVM" if a_val == "mvvm" else "Clean Architecture + MVI")
        di_str = "Koin" if d_val == "koin" else ("Hilt" if d_val == "hilt" else "Manual DI")
        nav_str = "Voyager" if n_val == "voyager" else ("Compose Navigation" if n_val == "comp" else "Decompose")
        ui_str = "Compose Material3" if u_val == "compose" else "XML Views"
        db_str = "Room" if db_val == "room" else ("SQLDelight" if db_val == "sql" else ("DataStore" if db_val == "datastore" else "No DB"))
        net_str = "Ktor" if net_val == "ktor" else ("Retrofit" if net_val == "retrofit" else "No API")

        stack = f"{plat_str} + {arch_str} + {di_str} + {nav_str} + {ui_str} + {db_str} + {net_str}"
        arch_mode = "greenfield_bootstrap"
        locales = "values, values-ar" if loc_val == "dual" else ("values" if loc_val == "en" else "values-ar")
        bootstrap_details = {
            "platform": p_val,
            "architecture": a_val,
            "di": d_val,
            "navigation": n_val,
            "ui": u_val,
            "database": db_val,
            "networking": net_val,
            "locales": loc_val,
        }
    tools = raw.get("i14") or []
    if isinstance(tools, str):
        tools = [x.strip() for x in tools.split(",") if x.strip()]
    if "all" in tools:
        tools = list(TOOL_IDS)
    tools = [x for x in tools if x in TOOL_IDS]
    if not tools:
        raise SystemExit("Pick at least one coding tool (I.14).")
    device = raw.get("i4") or auto["device_policy"]
    if device in {"allow-explicit", "allow", "skip"}:
        device = "allow"
    git_policy = raw.get("i3") or "never"
    if git_policy not in {"never", "agent-may-commit"}:
        git_policy = "never"
    zoho = raw.get("i16") or "skip"
    if zoho not in {"enable", "skip"}:
        zoho = "skip"
    chat_lang = raw.get("i17") or auto.get("chat_language") or "en"
    if chat_lang not in {"en", "mirror", "ar"}:
        chat_lang = "en"
    zoho_lang = raw.get("i18") or auto.get("zoho_language") or "en_titles_ar_comments"
    if zoho_lang not in {"en_titles_ar_comments", "all_en", "all_ar"}:
        zoho_lang = "en_titles_ar_comments"
    pm_provider = str(raw.get("i20") or auto.get("pm_provider") or DEFAULT_PM_PROVIDER).strip()
    if pm_provider not in PM_PROVIDER_IDS:
        raise SystemExit(
            f"Unknown project tracker '{pm_provider}'. Known: {', '.join(PM_PROVIDER_IDS)}"
        )
    discovered_flavors = [str(f) for f in (facts.get("flavors") or [])]
    flavor = str(raw.get("i19") or "").strip()
    if flavor in ("", "default"):
        flavor = ""
    if discovered_flavors and flavor and flavor not in discovered_flavors:
        raise SystemExit(f"Unknown flavor '{flavor}'. Known: {', '.join(discovered_flavors)}")
    assemble_tasks = (
        {f: f"{module}:assemble{_flavor_pascal(f)}Debug" for f in discovered_flavors}
        if module
        else {}
    )
    gemini = raw.get("i12") or auto["gemini_config"]
    if not facts.get("gemini"):
        gemini = "skip"
    asked = sorted(
        k for k in raw if isinstance(k, str) and (re.fullmatch(r"i\d+[a-z]?", k) or re.fullmatch(r"b_[a-z]+", k))
    )
    return {
        "schema": SCHEMA,
        "i0": True,
        "backup": do_backup,
        "product": product,
        "py": py,
        "git_policy": git_policy,
        "device_policy": device,
        "module": module,
        "assemble": f"{module}:assembleDebug",
        "flavor": flavor,
        "assemble_tasks": assemble_tasks,
        "launcher": launcher,
        "apk": apk,
        "apk_path": apk_path,
        "architecture": stack if arch_mode in ("discovered", "greenfield_bootstrap") else "kit MVI/Hilt/Room leftovers",
        "architecture_mode": arch_mode,
        "bootstrap_details": bootstrap_details,
        "locales": locales,
        "scaffold": "disable",
        "install_confirm": raw.get("i10") or auto["install_confirm"],
        "agents_git": "gitignore",
        "gemini_config": gemini,
        "assemble_now": raw.get("i13") or auto["assemble_now"],
        "unit_tests": "yes" if (raw.get("i15") or auto.get("unit_tests")) == "yes" else "no",
        "zoho_mcp": zoho,
        "chat_language": chat_lang,
        "zoho_language": zoho_lang,
        "pm_provider": pm_provider,
        "tools": tools,
        "git_gate": "no" if (raw.get("i21") or auto.get("git_gate", "yes")) == "no" else "yes",
        "asked": asked,
    }


def write_answers(repo: Path, answers: dict) -> None:
    dest = setup_dir(repo)
    dest.mkdir(parents=True, exist_ok=True)
    answers_path(repo).write_text(
        json.dumps(answers, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    md = [
        "# SETUP_ANSWERS",
        "",
        f"- I.0 Continue install: {'yes' if answers.get('i0') else 'no'}",
        f"- I.0 Backup: {'yes' if answers.get('backup', True) else 'no'}",
        f"- I.1 Product: {answers.get('product')}",
        f"- I.2 Python: {answers.get('py')}",
        f"- I.3 Git: {answers.get('git_policy')}",
        f"- I.4 Device: {answers.get('device_policy')}",
        f"- I.5 Module: {answers.get('module')}",
        f"- I.5 assemble: {answers.get('assemble')}",
        f"- I.6 Launcher: {answers.get('launcher')}",
        f"- I.6b APK: {answers.get('apk')} {answers.get('apk_path')}",
        f"- I.7 Architecture ({answers.get('architecture_mode')}): {answers.get('architecture')}",
        f"- I.8 Locales: {answers.get('locales')}",
        f"- I.9 Scaffold: {answers.get('scaffold')}",
        f"- I.10 Unattended install: {answers.get('install_confirm')}",
        f"- I.11 .agents in git: {answers.get('agents_git')}",
        f"- I.12 Gemini config: {answers.get('gemini_config')}",
        f"- I.13 Assemble now: {answers.get('assemble_now')}",
        f"- I.15 Unit tests: {answers.get('unit_tests')}",
        f"- I.16 Zoho Sprints: {answers.get('zoho_mcp')}",
        f"- I.17 Chat & Engineering Language: {answers.get('chat_language', 'en')}",
        f"- I.18 Zoho Updates Language: {answers.get('zoho_language', 'en_titles_ar_comments')}",
        f"- I.19 Daily flavor: {answers.get('flavor') or '(default variant)'}",
        f"- I.20 Project tracker: {answers.get('pm_provider') or DEFAULT_PM_PROVIDER}",
        f"- I.21 Pre-commit git gate: {answers.get('git_gate', 'yes')}",
        f"- Assemble tasks per flavor: {json.dumps(answers.get('assemble_tasks') or {}, ensure_ascii=False)}",
        f"- I.14 Tools: {', '.join(answers.get('tools') or [])}",
        f"- Asked in wizard: {', '.join(answers.get('asked') or ['(none recorded)'])}",
        "",
    ]
    if answers.get("bootstrap_details"):
        b = answers["bootstrap_details"]
        md.extend([
            "## Greenfield Bootstrap Details",
            f"- Platform: {b.get('platform')}",
            f"- Architecture: {b.get('architecture')}",
            f"- DI: {b.get('di')}",
            f"- Navigation: {b.get('navigation')}",
            f"- UI: {b.get('ui')}",
            f"- Database: {b.get('database')}",
            f"- Networking: {b.get('networking')}",
            f"- Locales: {b.get('locales')}",
            "",
        ])
    markdown_path(repo).write_text("\n".join(md), encoding="utf-8")
    gi = repo / ".gitignore"
    extra = [".harness-setup/", ".harness-backup/", ".agents/"]
    lines = read_text(gi).splitlines()
    for line in extra:
        if line not in lines:
            lines.append(line)
    text = "\n".join(lines)
    if text:
        text += "\n"
    gi.write_text(text, encoding="utf-8")

    # Local exclude: keep .githooks/ local to developer PC so team working trees stay clean
    exclude_path = repo / ".git" / "info" / "exclude"
    if (repo / ".git").is_dir() or exclude_path.is_file():
        try:
            exclude_path.parent.mkdir(parents=True, exist_ok=True)
            ex_text = exclude_path.read_text(encoding="utf-8") if exclude_path.is_file() else ""
            ex_lines = [ln.strip() for ln in ex_text.splitlines()]
            if ".githooks/" not in ex_lines and ".githooks" not in ex_lines:
                with exclude_path.open("a", encoding="utf-8", newline="\n") as f:
                    if ex_text and not ex_text.endswith("\n"):
                        f.write("\n")
                    f.write(".githooks/\n")
        except Exception:
            pass

    # If .githooks/pre-commit is tracked in git history, mark it assume-unchanged so it never dirties working trees
    subprocess.run(
        ["git", "update-index", "--assume-unchanged", ".githooks/pre-commit"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )


def flags_from_answers(answers: dict) -> str:
    tools = ",".join(answers.get("tools") or [])
    gate_flag = "--git-gate" if (answers.get("git_gate") or "yes") != "no" else "--no-git-gate"
    return (
        f"--product {answers['product']} --py {answers['py']} "
        f"--assemble {answers['assemble']} --device-policy {answers['device_policy']} "
        f"--git-policy {answers['git_policy']} --tools {tools} {gate_flag}"
    )


def pm_next_steps(answers: dict) -> list[str]:
    """Deterministic post-install guidance for the selected project tracker."""
    provider = str((answers or {}).get("pm_provider") or DEFAULT_PM_PROVIDER).strip()
    if provider == "github_projects":
        return [
            "PM: GitHub Projects selected (trigger phrase: update github).",
            "Verify the gh CLI when convenient:",
            "  python .agents/scripts/pm_github.py check",
            "Auth stays with gh ('gh auth login'); never paste tokens into the repo.",
        ]
    if provider == "jira_mcp":
        return [
            "PM: Jira MCP selected (trigger phrase: update jira).",
            "Registration guide: .agents/pm/mcp_registration.jira.md",
            "Credentials stay in ~/.android-harness/jira.json; never in the repo.",
        ]
    if provider == "linear_mcp":
        return [
            "PM: Linear MCP selected (trigger phrase: update linear).",
            "Registration guide: .agents/pm/mcp_registration.linear.md",
            "Credentials stay in ~/.android-harness/linear.json; never in the repo.",
        ]
    if provider == "none":
        return ["PM: no tracker selected; delivery stays local-only."]
    return []


def existing_defaults(repo: Path) -> dict[str, object]:
    """Map a previous answers.json to question ids so re-runs pre-fill them."""
    path = answers_path(repo)
    if not path.is_file():
        return {}
    try:
        answers = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(answers, dict) or not answers.get("i0"):
        return {}
    defaults: dict[str, object] = {"i0": "yes" if answers.get("backup", True) else "skip", "i1": "discovered"}
    for qid, field in (
        ("i2", "py"),
        ("i3", "git_policy"),
        ("i4", "device_policy"),
        ("i5", "module"),
        ("i6", "launcher"),
        ("i10", "install_confirm"),
        ("i15", "unit_tests"),
        ("i16", "zoho_mcp"),
        ("i17", "chat_language"),
        ("i18", "zoho_language"),
        ("i19", "flavor"),
        ("i20", "pm_provider"),
        ("i21", "git_gate"),
    ):
        value = answers.get(field)
        if value:
            defaults[qid] = value
    tools = answers.get("tools")
    if isinstance(tools, list) and tools:
        defaults["i14"] = list(tools)
    return defaults


def interactive(repo: Path, lang: str) -> dict:
    facts = discover(repo)
    defaults = existing_defaults(repo)
    print(t(lang, "model_warning"))
    print()
    print(auto_blurb(facts, lang))
    if defaults:
        print(t(lang, "defaults_note"))
    raw: dict = {}
    for q in questions_payload(repo, lang, facts):
        chosen = prompt_choice(q, lang, default_for_question(q, defaults))
        if q["id"] == "i0" and chosen[0] == "no":
            print(t(lang, "stopped"))
            raise SystemExit(1)
        if q.get("allow_multiple"):
            raw[q["id"]] = chosen
        else:
            raw[q["id"]] = chosen[0]
            if chosen[0] == "other":
                raw[q["id"] + "_text"] = prompt_text(lang)
            if q["id"] == "i1" and chosen[0] == "other":
                pass
        if q["id"] == "i2" and chosen[0] == "stop":
            print(t(lang, "no_python"))
            raise SystemExit(1)
    return normalize(raw, facts)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Record Android harness setup answers.")
    p.add_argument("--repo", help="Android checkout root.")
    p.add_argument("--lang", choices=("en", "ar"), default="en")
    p.add_argument(
        "command",
        nargs="?",
        default="ask",
        choices=("ask", "discover", "questions", "write", "flags"),
    )
    p.add_argument("--answers-json", help="For write: JSON object of question ids to values.")
    return p.parse_args(argv)


def find_repo(explicit: str | None) -> Path:
    if explicit:
        repo = Path(explicit).resolve()
    else:
        repo = Path.cwd().resolve()
    if not ((repo / "gradlew").is_file() or (repo / "gradlew.bat").is_file()):
        raise SystemExit(
            "[ERROR] Target directory is NOT an Android project. Missing gradlew / gradlew.bat. "
            "Please pass --repo pointing to a valid Android or Kotlin Multiplatform (KMP) project."
        )
    return repo


def load_write_payload(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("answers JSON must be an object.")
    return data


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except OSError:
            pass
    args = parse_args(argv)
    repo = find_repo(args.repo)
    if args.command == "discover":
        print(json.dumps(discover(repo), indent=2, ensure_ascii=False))
        return 0
    if args.command == "questions":
        facts = discover(repo)
        payload = {
            "discover": facts,
            "auto": auto_from_facts(facts),
            "model_warning": t(args.lang, "model_warning"),
            "auto_blurb": auto_blurb(facts, args.lang),
            "questions": questions_payload(repo, args.lang, facts),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if args.command == "flags":
        path = answers_path(repo)
        if not path.is_file():
            raise SystemExit(f"Missing {path}")
        answers = json.loads(path.read_text(encoding="utf-8"))
        print(flags_from_answers(answers))
        return 0
    if args.command == "write":
        if not args.answers_json:
            raise SystemExit("write needs --answers-json")
        raw = load_write_payload(Path(args.answers_json))
        if raw.get("schema") == SCHEMA and raw.get("i0") is True and "product" in raw:
            answers = raw
        else:
            answers = normalize(raw, discover(repo))
        if not answers.get("i0"):
            print(t(args.lang, "stopped"))
            return 1
        write_answers(repo, answers)
        print(t(args.lang, "wrote", path=str(answers_path(repo))))
        print("installer flags:", flags_from_answers(answers))
        for line in pm_next_steps(answers):
            print(line)
        return 0
    answers = interactive(repo, args.lang)
    write_answers(repo, answers)
    print(t(args.lang, "wrote", path=str(answers_path(repo))))
    print("installer flags:", flags_from_answers(answers))
    for line in pm_next_steps(answers):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
