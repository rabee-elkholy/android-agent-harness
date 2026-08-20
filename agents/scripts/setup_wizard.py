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
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCHEMA = 1
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
            "Setup will replace .agents in this repo. A backup plus the rollback prompt "
            "can restore what is here today. Without a backup, the old harness is gone. "
            "Do you want to back up and start?"
        ),
        "i0_yes": "Yes, back up and start",
        "i0_no": "No, stop",
        "i1": (
            "Reviewer prompts and AGENTS.md will use this name. If we keep the example "
            "product name, reviews talk about the wrong app. Use the name I found, or type another?"
        ),
        "i1_use": "Use “{name}”",
        "i1_other": "Other name (I will type it)",
        "i2": (
            "Every harness script starts with this command. On Windows, python3 is often a "
            "Store stub that does not run. The one I verified actually works. Pick it, or stop "
            "so you can install Python 3.10+."
        ),
        "i2_stop": "Stop — install Python 3.10+",
        "i3": (
            "The default blocks the agent from git add / commit / push so nothing lands on "
            "GitHub unless you commit in the IDE. If you want the agent to commit when you ask "
            "in chat, pick the second option. Surprise commits are the failure mode of the second choice."
        ),
        "i3_never": "Agent never touches git (developer commits) (Recommended)",
        "i3_may": "Agent may commit when I explicitly ask",
        "i4": (
            "This chooses whether the harness may use an emulator serial. Pick “both allowed” "
            "unless you are sure you will never debug on an AVD. “Physical only” blocks emulator "
            "installs and logcat. You can change this later with the update prompt. Skipping is safe."
        ),
        "i4_skip": "Skip — both allowed for now (Recommended)",
        "i4_allow": "Allow emulator",
        "i4_phys": "Physical device only",
        "i5": (
            "Assemble and install must use the module that actually builds the APK. The wrong "
            "module means you install an old or missing APK. I found these application modules."
        ),
        "i5_other": "Other module (I will type it)",
        "i6": (
            "After install, run_device.py starts this activity (package/.Activity). The wrong "
            "component opens a blank task or a different screen. I found these MAIN/LAUNCHER activities."
        ),
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
            "run_device.py overwrites the app on the phone. Confirm-before-install avoids a surprise "
            "install on the wrong device. Skipping confirm is faster if you trust the allowlist."
        ),
        "i10_conf": "Confirm before adb install (Recommended)",
        "i10_allow": "Allow run_device.py without confirm",
        "i11": (
            "Gitignore keeps the harness on this machine only (clones will not get .agents). "
            "Committing it later shares the engine with the team, still without state/. This setup "
            "will not commit unless you later say commit."
        ),
        "i11_gi": "Add to .gitignore (local)",
        "i11_later": "We will commit it later without state/",
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
            "Each tool loads a different file (Cursor .mdc, GEMINI.md, CLAUDE.md, Copilot, …). Pick "
            "every product you actually open this repo in. If you use Cursor but only pick Gemini, "
            "Cursor will not get .cursor/rules. Extra tools only add files; you can add one later. "
            "Do not pick all just to be safe if you want a clean root. Comma-separated numbers, or all."
        ),
        "type_value": "Type the value:",
        "pick": "Enter number",
        "pick_multi": "Enter numbers (comma-separated)",
        "invalid": "Invalid choice.",
        "stopped": "Stopped. No answers written.",
        "wrote": "Wrote {path}",
        "no_python": "No working Python 3.10+ on PATH.",
        "need_repo": "Need --repo pointing at an Android checkout with gradlew.",
    },
    "ar": {
        "i0": (
            "التثبيت هيبَدّل مجلد .agents في المشروع. لو عملنا نسخة احتياطية نقدر نرجّع النظام القديم "
            "ببرومبت الـ rollback. من غير نسخة، النظام القديم يضيع. نعمل backup ونبدأ؟"
        ),
        "i0_yes": "نعم، backup ونبدأ",
        "i0_no": "لا، وقف",
        "i1": (
            "اسم المنتج هيظهر في AGENTS.md وفي المراجعين. لو سيبنا اسم المثال، المراجعات هتتكلم عن "
            "أبلكيشن تاني. نستخدم الاسم اللي لقيته، ولا تكتب اسم تاني؟"
        ),
        "i1_use": "استخدم «{name}»",
        "i1_other": "اسم تاني (هكتبه)",
        "i2": (
            "كل سكربتات الـ harness بتبدأ بالأمر ده. على ويندوز python3 غالباً اختصار من الـ Store "
            "ومش بيشتغل. الأمر اللي اتأكدت إنه شغال قدامك. اختاره، أو وقف وثبّت Python 3.10+."
        ),
        "i2_stop": "قف — ثبّت Python 3.10+",
        "i3": (
            "الافتراضي يمنع الوكيل من git add / commit / push عشان ما يرفعش حاجة من غيرك. لو عايز "
            "الوكيل يعمل كوميت لما تطلب في الشات، الخيار الثاني. مفاجأة كوميت هي غلطة الخيار الثاني."
        ),
        "i3_never": "الوكيل ما يلمسش git (أنت اللي بتعمل كوميت) (مفضّل)",
        "i3_may": "الوكيل يعمل كوميت لما أطلب صراحة",
        "i4": (
            "هل الـ harness يستخدم محاكي؟ «الاتنين مسموحين» إلا لو أكيد مش هتدِبَج على AVD. "
            "«موبايل بس» بيمنع تثبيت ولوجكات المحاكي. تقدر تغيّر بعدين ببرومبت التحديث. التخطي آمن."
        ),
        "i4_skip": "تخطّي — الاتنين مسموحين دلوقتي (مفضّل)",
        "i4_allow": "اسمح بالمحاكي",
        "i4_phys": "موبايل حقيقي فقط",
        "i5": (
            "الـ assemble والتثبيت لازم على الموديول اللي فعلاً بيطلع الـ APK. الموديول الغلط يعني "
            "تثبيت APK قديم أو مش موجود. لقيت موديولات التطبيق دي."
        ),
        "i5_other": "موديول تاني (هكتبه)",
        "i6": (
            "بعد التثبيت run_device.py بيفتح الشاشة دي (package/.Activity). المكوّن الغلط يفتح شاشة "
            "فاضية أو شاشة تانية. لقيت MAIN/LAUNCHER دول."
        ),
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
            "run_device.py بيستبدل التطبيق على الموبايل. التأكيد قبل التثبيت يمنع تثبيت على جهاز غلط. "
            "من غير تأكيد أسرع لو واثق من الـ allowlist."
        ),
        "i10_conf": "أكّد قبل adb install (مفضّل)",
        "i10_allow": "اسمح لـ run_device.py من غير تأكيد",
        "i11": (
            "gitignore يخلي الـ harness على الجهاز ده بس (الـ clone مش هيبقى فيه .agents). "
            "لو هتعملوا كوميت بعدين، الفريق يشاركه من غير state/. التثبيت الحالي مش هيعمل كوميت."
        ),
        "i11_gi": "ضيف لـ .gitignore (محلي)",
        "i11_later": "هنعمل كوميت بعدين من غير state/",
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
            "كل أداة بتقرا ملف مختلف (Cursor .mdc، GEMINI.md، CLAUDE.md، Copilot…). اختار كل أداة "
            "بتفتح بيها المشروع. لو بتستخدم Cursor وتختار Gemini بس، Cursor مش هياخد .cursor/rules. "
            "تقدر تضيف أداة بعدين. متختارش «كلهم» لو عايز روت نضيف. أرقام مفصولة بفاصلة، أو all."
        ),
        "type_value": "اكتب القيمة:",
        "pick": "اكتب الرقم",
        "pick_multi": "اكتب الأرقام مفصولة بفاصلة",
        "invalid": "اختيار غلط.",
        "stopped": "اتوقف. مفيش إجابات اتكتبت.",
        "wrote": "اتكتب {path}",
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
        for m in re.finditer(r'applicationId\s*=\s*["\']([^"\']+)["\']', text):
            if m.group(1) not in ids:
                ids.append(m.group(1))
        for m in re.finditer(r'namespace\s*=\s*["\']([^"\']+)["\']', text):
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


def gemini_exists() -> bool:
    return (Path.home() / ".gemini" / "config.json").is_file() or (
        Path.home() / ".gemini" / "config" / "config.json"
    ).is_file()


def discover(repo: Path) -> dict:
    modules = discover_modules(repo)
    pythons = discover_pythons()
    locales = discover_locales(repo)
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
        "gradlew": (repo / "gradlew").is_file() or (repo / "gradlew.bat").is_file(),
    }


def questions_payload(repo: Path, lang: str) -> list[dict]:
    d = discover(repo)
    L = "ar" if lang == "ar" else "en"
    labels = TOOL_LABELS[L]
    py_opts = [{"id": p, "label": p} for p in d["pythons"]]
    py_opts.append({"id": "stop", "label": t(lang, "i2_stop")})
    mod_opts = [{"id": m, "label": m} for m in d["modules"]]
    mod_opts.append({"id": "other", "label": t(lang, "i5_other")})
    launch_opts = [{"id": x, "label": x} for x in d["launchers"]]
    launch_opts.append({"id": "other", "label": t(lang, "i6_other")})
    apk_opts = []
    if d["apk_hint"]:
        apk_opts.append({"id": "discovered", "label": t(lang, "i6b_use", path=d["apk_hint"])})
    apk_opts.append({"id": "glob", "label": t(lang, "i6b_glob")})
    apk_opts.append({"id": "other", "label": t(lang, "i6b_other")})
    loc_label = ", ".join(d["locales"]) if d["locales"] else "values"
    qs = [
        {
            "id": "i0",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i0"),
            "options": [
                {"id": "yes", "label": t(lang, "i0_yes")},
                {"id": "no", "label": t(lang, "i0_no")},
            ],
        },
        {
            "id": "i1",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i1"),
            "options": [
                {"id": "discovered", "label": t(lang, "i1_use", name=d["product"])},
                {"id": "other", "label": t(lang, "i1_other")},
            ],
        },
        {
            "id": "i2",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i2"),
            "options": py_opts,
        },
        {
            "id": "i3",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i3"),
            "options": [
                {"id": "never", "label": t(lang, "i3_never")},
                {"id": "agent-may-commit", "label": t(lang, "i3_may")},
            ],
        },
        {
            "id": "i4",
            "required": False,
            "allow_multiple": False,
            "prompt": t(lang, "i4"),
            "options": [
                {"id": "allow", "label": t(lang, "i4_skip")},
                {"id": "allow-explicit", "label": t(lang, "i4_allow")},
                {"id": "physical-only", "label": t(lang, "i4_phys")},
            ],
        },
        {
            "id": "i5",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i5"),
            "options": mod_opts,
        },
        {
            "id": "i6",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i6"),
            "options": launch_opts,
        },
        {
            "id": "i6b",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i6b"),
            "options": apk_opts,
        },
        {
            "id": "i7",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i7"),
            "options": [
                {"id": "discovered", "label": t(lang, "i7_use", stack=d["stack"])},
                {"id": "keep-kit", "label": t(lang, "i7_keep")},
            ],
        },
        {
            "id": "i8",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i8"),
            "options": [
                {"id": "discovered", "label": t(lang, "i8_use", folders=loc_label)},
                {"id": "other", "label": t(lang, "i8_other")},
            ],
        },
        {
            "id": "i9",
            "required": False,
            "allow_multiple": False,
            "prompt": t(lang, "i9"),
            "options": [
                {"id": "disable", "label": t(lang, "i9_dis")},
                {"id": "retarget", "label": t(lang, "i9_ret")},
            ],
        },
        {
            "id": "i10",
            "required": False,
            "allow_multiple": False,
            "prompt": t(lang, "i10"),
            "options": [
                {"id": "confirm", "label": t(lang, "i10_conf")},
                {"id": "allow", "label": t(lang, "i10_allow")},
            ],
        },
        {
            "id": "i11",
            "required": False,
            "allow_multiple": False,
            "prompt": t(lang, "i11"),
            "options": [
                {"id": "gitignore", "label": t(lang, "i11_gi")},
                {"id": "commit-later", "label": t(lang, "i11_later")},
            ],
        },
    ]
    if d["gemini"]:
        qs.append(
            {
                "id": "i12",
                "required": True,
                "allow_multiple": False,
                "prompt": t(lang, "i12"),
                "options": [
                    {"id": "merge-allowlist", "label": t(lang, "i12_merge")},
                    {"id": "global-rule", "label": t(lang, "i12_global")},
                ],
            }
        )
    qs.append(
        {
            "id": "i13",
            "required": False,
            "allow_multiple": False,
            "prompt": t(lang, "i13"),
            "options": [
                {"id": "tests-only", "label": t(lang, "i13_tests")},
                {"id": "assemble", "label": t(lang, "i13_asm")},
            ],
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
    return qs


def prompt_choice(q: dict, lang: str) -> list[str]:
    print()
    print(q["prompt"])
    print()
    for i, opt in enumerate(q["options"], start=1):
        print(f"  {i}) {opt['label']}")
    hint = t(lang, "pick_multi" if q.get("allow_multiple") else "pick")
    if not q.get("required"):
        hint += " [Enter = 1]"
    while True:
        raw = input(f"{hint}: ").strip()
        if not raw and not q.get("required"):
            return [q["options"][0]["id"]]
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
        return {"schema": SCHEMA, "i0": False}
    py = raw.get("i2")
    if py in (None, "stop"):
        raise SystemExit("Python command missing or stop selected.")
    module = raw.get("i5")
    if module == "other":
        module = raw.get("i5_text") or ""
    if module and not module.startswith(":"):
        module = ":" + module
    launcher = raw.get("i6")
    if launcher == "other":
        launcher = raw.get("i6_text") or ""
    apk = raw.get("i6b")
    apk_path = facts.get("apk_hint") or "**/outputs/apk/debug/*.apk"
    if apk == "other":
        apk_path = raw.get("i6b_text") or apk_path
        apk = "path"
    elif apk == "discovered":
        apk = "path"
    elif apk != "glob":
        apk = "glob"
        apk_path = "**/outputs/apk/debug/*.apk"
    product = facts.get("product") or "App"
    if raw.get("i1") == "other":
        product = raw.get("i1_text") or product
    locales = ", ".join(facts.get("locales") or ["values"])
    if raw.get("i8") == "other":
        locales = raw.get("i8_text") or locales
    stack = facts.get("stack") or "unknown"
    arch_mode = "keep-kit" if raw.get("i7") == "keep-kit" else "discovered"
    tools = raw.get("i14") or []
    if isinstance(tools, str):
        tools = [x.strip() for x in tools.split(",") if x.strip()]
    if "all" in tools:
        tools = list(TOOL_IDS)
    tools = [x for x in tools if x in TOOL_IDS]
    if not tools:
        raise SystemExit("Pick at least one coding tool (I.14).")
    device = raw.get("i4") or "allow"
    if device in {"allow-explicit", "allow"}:
        device = "allow"
    git_policy = raw.get("i3") or "never"
    if git_policy not in {"never", "agent-may-commit"}:
        git_policy = "never"
    gemini = raw.get("i12") or "skip"
    if not facts.get("gemini"):
        gemini = "skip"
    return {
        "schema": SCHEMA,
        "i0": True,
        "product": product,
        "py": py,
        "git_policy": git_policy,
        "device_policy": device,
        "module": module,
        "assemble": f"{module}:assembleDebug",
        "launcher": launcher,
        "apk": apk,
        "apk_path": apk_path,
        "architecture": stack if arch_mode == "discovered" else "kit MVI/Hilt/Room leftovers",
        "architecture_mode": arch_mode,
        "locales": locales,
        "scaffold": raw.get("i9") or "disable",
        "install_confirm": raw.get("i10") or "confirm",
        "agents_git": raw.get("i11") or "gitignore",
        "gemini_config": gemini,
        "assemble_now": raw.get("i13") or "tests-only",
        "tools": tools,
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
        f"- I.0 Backup and start: {'yes' if answers.get('i0') else 'no'}",
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
        f"- I.14 Tools: {', '.join(answers.get('tools') or [])}",
        "",
    ]
    markdown_path(repo).write_text("\n".join(md), encoding="utf-8")
    gi = repo / ".gitignore"
    extra = [".harness-setup/", ".harness-backup/"]
    existing = read_text(gi)
    add = [line for line in extra if line not in existing.splitlines()]
    if add:
        prefix = "" if existing.endswith("\n") or not existing else "\n"
        with gi.open("a", encoding="utf-8") as fh:
            fh.write(prefix + "\n".join(add) + "\n")


def flags_from_answers(answers: dict) -> str:
    tools = ",".join(answers.get("tools") or [])
    return (
        f"--product {answers['product']} --py {answers['py']} "
        f"--assemble {answers['assemble']} --device-policy {answers['device_policy']} "
        f"--git-policy {answers['git_policy']} --tools {tools}"
    )


def interactive(repo: Path, lang: str) -> dict:
    facts = discover(repo)
    raw: dict = {}
    for q in questions_payload(repo, lang):
        chosen = prompt_choice(q, lang)
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
        raise SystemExit("Pass --repo <android-checkout> with gradlew / gradlew.bat.")
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
        payload = {"discover": discover(repo), "questions": questions_payload(repo, args.lang)}
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
        return 0
    answers = interactive(repo, args.lang)
    write_answers(repo, answers)
    print(t(args.lang, "wrote", path=str(answers_path(repo))))
    print("installer flags:", flags_from_answers(answers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
