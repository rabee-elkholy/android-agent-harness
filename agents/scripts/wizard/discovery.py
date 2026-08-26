"""Discovery engine for Gradle modules, launchers, product flavors, and project stack."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from .i18n import DEFAULT_PM_PROVIDER, SKIP_DIRS, t


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
    mcp = Path(__file__).resolve().parent.parent.parent / "mcp" / "zoho_sprints"
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
