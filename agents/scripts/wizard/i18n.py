"""Wizard strings (English-first) and constants.

Client-facing prose mirrors the developer's conversation language: chat-rendered
questions are localized by the installing agent. The only bilingual exception is
the tracker-language question (I.18), kept for Zoho compatibility.
"""
from __future__ import annotations

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
        "i18": (
            "What is your preferred language for task tracker descriptions and comments (Zoho / Jira / Linear / GitHub)?"
        ),
        "i18_en_titles_ar_comments": "English task titles + Arabic comments and descriptions (Recommended for bilingual teams)",
        "i18_all_en": "All English (Titles, descriptions, and comments in English)",
        "i18_all_ar": "All Arabic (Titles, descriptions, and comments in Arabic)",
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
        "i22": (
            "Device Verification Mode: How should the harness verify the app on the connected device after building? "
            "Autonomous E2E explores, clicks, and asserts UI responsiveness on the phone before asking for your sign-off. "
            "Manual-only launches the app and presents step-by-step test instructions for you to try."
        ),
        "i22_manual": "Manual Smoke Test — App is launched on device; you follow simple steps and confirm (Recommended)",
        "i22_e2e": "Autonomous E2E Smoke Test — AI Agent runs automated UI flows on device via Maestro",
        "i22_off": "No device verification — assemble only (I test manually outside the harness)",
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
        "i18": (
            "ما هي اللغة المفضلة لتحديثات ووصف وتعليقات مهام نظام إدارة المشاريع (Zoho / Jira / Linear / GitHub)؟"
        ),
        "i18_en_titles_ar_comments": "عناوين المهام بالإنجليزي والوصف/التعليقات بالعربي (مفضّل لفرق العمل)",
        "i18_all_en": "إنجليزي بالكامل (العناوين والوصف والتعليقات بالإنجليزي)",
        "i18_all_ar": "عربي بالكامل",
    },
}


def t(lang: str, key: str, **kwargs: str) -> str:
    table = T.get(lang, T["en"]) if lang == "ar" else T["en"]
    entry = table.get(key, T["en"].get(key, ""))
    return entry.format(**kwargs)
