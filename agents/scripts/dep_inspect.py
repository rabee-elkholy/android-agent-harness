#!/usr/bin/env python3
"""Read-only Third-Party Dependency & Library Source Inspector (`harness.py dep-inspect`).

Inspects Kotlin/Java APIs, KDoc, and declarations of external Gradle dependencies
without waiting for Android Studio Sync and without dumping raw JVM bytecode:
1. Resolves `<group:artifact:version>` (or auto-discovers `<group>` / `<version>` from
   `gradle/libs.versions.toml` and `build.gradle*`).
2. Checks local Gradle caches (`GRADLE_USER_HOME`, `JAVA_HOME` sibling caches, `~/.gradle`).
3. When `-sources.jar` is not cached locally yet (e.g. before Android Studio Sync),
   fetches `<artifact>-<version>-sources.jar` (including KMP `-android` / `-jvm` variants)
   directly from Google Maven / Maven Central into `.agents/state/cache/dep-sources/`.
4. Extracts token-bounded Kotlin/Java declarations and KDoc (stripping `import` noise),
   falling back to clean `javap -public` signatures (never raw bytecode) for closed-source SDKs.

Zero external dependencies (Python 3.10+ stdlib only).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import ValidationError, configure_utf8_output, state_root  # noqa: E402

MAX_DOWNLOAD_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_CHARS = 6500
HARD_MAX_CHARS = 20000
NETWORK_TIMEOUT_SECONDS = 8.0

PUBLIC_MAVEN_REPOS: tuple[str, ...] = (
    "https://dl.google.com/android/maven2",
    "https://repo1.maven.org/maven2",
)
JITPACK_REPO = "https://jitpack.io"

_SYNTHETIC_CLASS_NOISE_RE = re.compile(
    r"(?:\$WhenMappings|\$\$serializer|\$DefaultImpls|\$lambda\$|\$inlined\$|\$[0-9]+)(?:\$|\.class$)"
)
_DECL_LINE_RE = re.compile(
    r"^\s*(?:@[A-Za-z0-9_.]+\s*)*(?:public\s+|internal\s+|protected\s+|private\s+|open\s+|abstract\s+|sealed\s+|data\s+|value\s+|inline\s+|suspend\s+|operator\s+|infix\s+)*"
    r"(?:class|interface|object|fun|val|var|typealias|enum\s+class|annotation\s+class)\s+([A-Za-z0-9_`]+)"
)
_COORD_LITERAL_RE = re.compile(
    r"""['"]([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+):([^'"\s$]+|\$\{?[A-Za-z0-9_.-]+\}?)['"]"""
)
_GROOVY_OR_KTS_VAR_RE = re.compile(
    r"""^\s*(?:val|var|def|ext\.)?\s*([A-Za-z0-9_]+)\s*=\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)


def _discover_gradle_files21_roots(repo: Path, extra_cache_dirs: list[Path] | None = None) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    def _add(cand: Path) -> None:
        try:
            resolved = cand.expanduser().resolve()
        except OSError:
            return
        key = str(resolved).lower()
        if key not in seen and resolved.is_dir():
            seen.add(key)
            roots.append(resolved)

    for extra in extra_cache_dirs or []:
        if (extra / "caches" / "modules-2" / "files-2.1").is_dir():
            _add(extra / "caches" / "modules-2" / "files-2.1")
        else:
            _add(extra)

    env_guh = os.environ.get("GRADLE_USER_HOME", "").strip()
    if env_guh:
        _add(Path(env_guh) / "caches" / "modules-2" / "files-2.1")

    # Windows Android setups frequently place `.gradle_windows/jdks/...` and `.gradle_windows/caches/...` side by side
    env_jh = os.environ.get("JAVA_HOME", "").strip()
    if env_jh:
        jh_path = Path(env_jh)
        for anc in list(jh_path.parents)[:4]:
            _add(anc / "caches" / "modules-2" / "files-2.1")

    _add(Path.home() / ".gradle" / "caches" / "modules-2" / "files-2.1")
    _add(repo / ".gradle" / "caches" / "modules-2" / "files-2.1")
    return roots


def _dep_sources_cache_dir(repo: Path) -> Path:
    return state_root(repo) / "cache" / "dep-sources"



_COORD_VERSIONLESS_RE = re.compile(
    r"""(?:implementation|api|compileOnly|runtimeOnly|ksp|kapt|testImplementation|androidTestImplementation)\s*\(\s*['"]([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+)['"]\s*\)"""
)
_PLATFORM_COORD_RE = re.compile(
    r"""(?:enforcedPlatform|platform)\s*\(\s*['"]([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+):([^'"\s$]+|\$\{?[A-Za-z0-9_.-]+\}?)['"]\s*\)"""
)


def _parse_repo_catalog_and_boms(
    repo: Path,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]], list[tuple[str, str, str]]]:
    """Return `(versioned_deps, versionless_deps, declared_boms)` across `libs.versions.toml` and `build.gradle*`."""
    versioned: list[tuple[str, str, str]] = []
    seen_ver: set[tuple[str, str, str]] = set()
    versionless: list[tuple[str, str]] = []
    seen_vless: set[tuple[str, str]] = set()
    boms: list[tuple[str, str, str]] = []
    seen_boms: set[tuple[str, str, str]] = set()

    def _rec_ver(g: str, a: str, v: str, *, is_bom_hint: bool = False) -> None:
        tup = (g.strip(), a.strip(), v.strip())
        if tup[0] and tup[1] and tup[2] and not tup[2].startswith("$"):
            if tup not in seen_ver:
                seen_ver.add(tup)
                versioned.append(tup)
            if (is_bom_hint or tup[1].lower().endswith("-bom") or tup[1].lower() == "bom") and tup not in seen_boms:
                seen_boms.add(tup)
                boms.append(tup)

    def _rec_vless(g: str, a: str) -> None:
        tup = (g.strip(), a.strip())
        if tup[0] and tup[1] and tup not in seen_vless:
            seen_vless.add(tup)
            versionless.append(tup)

    for toml_rel in ("gradle/libs.versions.toml", "libs.versions.toml"):
        toml_p = repo / toml_rel
        if not toml_p.is_file():
            continue
        try:
            txt = toml_p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        versions_map: dict[str, str] = {}
        section = ""
        for raw_line in txt.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().lower()
                continue
            if section == "versions" and "=" in line:
                k, val = line.split("=", 1)
                v_clean = val.strip().strip("\"'")
                if k.strip() and v_clean:
                    versions_map[k.strip()] = v_clean
            elif section == "libraries" and "=" in line:
                alias_k, rhs = line.split("=", 1)
                alias_low = alias_k.strip().lower()
                rhs = rhs.strip()
                is_bom_alias = "bom" in alias_low
                if rhs.startswith(("\"", "'")):
                    parts = rhs.strip("\"'").split(":")
                    if len(parts) == 3:
                        _rec_ver(parts[0], parts[1], parts[2], is_bom_hint=is_bom_alias)
                    elif len(parts) == 2:
                        _rec_vless(parts[0], parts[1])
                elif rhs.startswith("{"):
                    m_mod = re.search(r"""module\s*=\s*['"]([^'"]+)['"]""", rhs)
                    m_grp = re.search(r"""group\s*=\s*['"]([^'"]+)['"]""", rhs)
                    m_nam = re.search(r"""name\s*=\s*['"]([^'"]+)['"]""", rhs)
                    m_vref = re.search(r"""version\.ref\s*=\s*['"]([^'"]+)['"]""", rhs)
                    m_ver = re.search(r"""(?<!\.)version\s*=\s*['"]([^'"]+)['"]""", rhs)
                    grp, art = "", ""
                    if m_mod and ":" in m_mod.group(1):
                        grp, art = m_mod.group(1).split(":", 1)
                    elif m_grp and m_nam:
                        grp, art = m_grp.group(1), m_nam.group(1)
                    ver = ""
                    if m_vref:
                        ver = versions_map.get(m_vref.group(1), "")
                    elif m_ver:
                        ver = m_ver.group(1)
                    if grp and art:
                        if ver:
                            _rec_ver(grp, art, ver, is_bom_hint=is_bom_alias)
                        else:
                            _rec_vless(grp, art)

    gradle_files: list[Path] = []
    seen_gf: set[Path] = set()
    skip_dirs = {"build", ".gradle", ".git", ".idea", "node_modules", ".agents"}

    def _add_gf(p: Path) -> None:
        if len(gradle_files) >= 120 or not p.is_file() or p.name not in {"build.gradle", "build.gradle.kts"}:
            return
        try:
            rel_parts = p.relative_to(repo).parts
        except ValueError:
            rel_parts = p.parts
        if any(part in skip_dirs for part in rel_parts):
            return
        if p not in seen_gf:
            seen_gf.add(p)
            gradle_files.append(p)

    for root_gf in ("build.gradle", "build.gradle.kts"):
        _add_gf(repo / root_gf)
    for pattern in ("*/build.gradle*", "*/*/build.gradle*", "*/*/*/build.gradle*"):
        for sub_gf in sorted(repo.glob(pattern)):
            _add_gf(sub_gf)
            if len(gradle_files) >= 120:
                break

    vars_map: dict[str, str] = {}
    file_texts: list[str] = []
    for gf in gradle_files:
        try:
            gtxt = gf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        file_texts.append(gtxt)
        for vm in _GROOVY_OR_KTS_VAR_RE.finditer(gtxt):
            vars_map[vm.group(1)] = vm.group(2)

    for gtxt in file_texts:
        for pm in _PLATFORM_COORD_RE.finditer(gtxt):
            grp, art, raw_v = pm.group(1), pm.group(2), pm.group(3)
            if raw_v.startswith("$"):
                raw_v = vars_map.get(raw_v.lstrip("$").strip("{}"), "")
            if raw_v:
                _rec_ver(grp, art, raw_v, is_bom_hint=True)
        for cm in _COORD_LITERAL_RE.finditer(gtxt):
            grp, art, raw_v = cm.group(1), cm.group(2), cm.group(3)
            if raw_v.startswith("$"):
                v_key = raw_v.lstrip("$").strip("{}")
                raw_v = vars_map.get(v_key, "")
            if raw_v:
                _rec_ver(grp, art, raw_v)
        for vlm in _COORD_VERSIONLESS_RE.finditer(gtxt):
            _rec_vless(vlm.group(1), vlm.group(2))

    return versioned, versionless, boms


def _load_or_fetch_bom_pom(
    repo: Path,
    bom_group: str,
    bom_artifact: str,
    bom_version: str,
    cache_roots: list[Path],
    *,
    offline: bool = False,
    maven_repos: list[str] | None = None,
) -> str:
    """Locate `<bom>-<version>.pom` in local caches or fetch from Maven repos."""
    local_cache = _dep_sources_cache_dir(repo)
    safe_pom = f"{bom_group}__{bom_artifact}__{bom_version}.pom".replace(":", "_")
    cached_pom = local_cache / safe_pom
    if cached_pom.is_file():
        try:
            return cached_pom.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

    for croot in cache_roots:
        ver_dir = croot / bom_group / bom_artifact / bom_version
        if ver_dir.is_dir():
            try:
                for cand in sorted(ver_dir.rglob(f"{bom_artifact}-{bom_version}.pom")):
                    if cand.is_file():
                        return cand.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

    if offline:
        return ""

    grp_path = bom_group.replace(".", "/")
    pom_name = f"{bom_artifact}-{bom_version}.pom"
    for base_url in _configured_maven_repos(repo, custom_repos=maven_repos):
        url = f"{base_url}/{grp_path}/{bom_artifact}/{bom_version}/{pom_name}"
        req = urllib.request.Request(url, headers={"User-Agent": "android-agent-harness-dep-inspect/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT_SECONDS) as resp:
                resp_status = getattr(resp, "status", None)
                if resp_status is not None and int(resp_status) != 200:
                    continue
                data = resp.read(2 * 1024 * 1024 + 1)
                if len(data) > 2 * 1024 * 1024:
                    continue
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
            continue
        try:
            local_cache.mkdir(parents=True, exist_ok=True)
            cached_pom.write_bytes(data)
        except OSError:
            pass
        return data.decode("utf-8", errors="replace")
    return ""


def _parse_bom_managed_versions(pom_xml: str, bom_version: str) -> dict[tuple[str, str], str]:
    """Extract `(groupId, artifactId) -> version` from a Maven BOM `.pom` `<dependencyManagement>` section."""
    import xml.etree.ElementTree as ET

    if not pom_xml.strip():
        return {}
    # Strip default XML namespaces for clean tag matching
    cleaned_xml = re.sub(r"""\sxmlns(?::[A-Za-z0-9_-]+)?=['"][^'"]*['"]""", "", pom_xml)
    try:
        root = ET.fromstring(cleaned_xml)
    except ET.ParseError:
        return {}

    props: dict[str, str] = {"project.version": bom_version, "pom.version": bom_version}
    props_el = root.find("properties")
    if props_el is not None:
        for child in props_el:
            tag = child.tag.split("}", 1)[-1].strip()
            val = (child.text or "").strip()
            if tag and val:
                props[tag] = val

    def _resolve_prop(raw_v: str) -> str:
        val = raw_v.strip()
        # Strip Maven version range brackets like `[1.4.0]` -> `1.4.0`
        if val.startswith("[") and val.endswith("]") and "," not in val:
            val = val[1:-1].strip()
        for _ in range(3):
            m_p = re.fullmatch(r"\$\{([^}]+)\}", val)
            if not m_p:
                break
            resolved = props.get(m_p.group(1).strip(), "")
            if not resolved:
                return ""
            val = resolved
        return "" if "$" in val else val

    managed: dict[tuple[str, str], str] = {}
    for dep_el in root.findall(".//dependencyManagement/dependencies/dependency"):
        g_txt = (dep_el.findtext("groupId") or "").strip()
        a_txt = (dep_el.findtext("artifactId") or "").strip()
        v_txt = _resolve_prop(dep_el.findtext("version") or "")
        if g_txt and a_txt and v_txt:
            managed[(g_txt, a_txt)] = v_txt
    return managed


def _resolve_version_from_boms(
    repo: Path,
    group: str,
    artifact: str,
    declared_boms: list[tuple[str, str, str]],
    cache_roots: list[Path],
    *,
    offline: bool = False,
    maven_repos: list[str] | None = None,
) -> str:
    if not declared_boms:
        return ""
    grp_prefix = ".".join(group.split(".")[:2])

    def _bom_priority(b: tuple[str, str, str]) -> int:
        bg = b[0]
        if bg == group:
            return 0
        if bg.startswith(grp_prefix) or group.startswith(bg):
            return 1
        return 2

    candidates = [artifact]
    if not artifact.endswith(("-android", "-jvm")):
        candidates.extend([f"{artifact}-android", f"{artifact}-jvm"])

    for bom_g, bom_a, bom_v in sorted(declared_boms, key=_bom_priority):
        pom_txt = _load_or_fetch_bom_pom(
            repo, bom_g, bom_a, bom_v, cache_roots, offline=offline, maven_repos=maven_repos
        )
        if not pom_txt:
            continue
        managed = _parse_bom_managed_versions(pom_txt, bom_v)
        for cand_art in candidates:
            ver = managed.get((group, cand_art))
            if ver:
                return ver
    return ""


def _parse_repo_declared_dependencies(repo: Path) -> list[tuple[str, str, str]]:
    """Scan `gradle/libs.versions.toml` and `build.gradle*` for `(group, artifact, version)` declarations."""
    found: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def _record(g: str, a: str, v: str) -> None:
        tup = (g.strip(), a.strip(), v.strip())
        if tup[0] and tup[1] and tup[2] and not tup[2].startswith("$") and tup not in seen:
            seen.add(tup)
            found.append(tup)

    # 1. `gradle/libs.versions.toml`
    for toml_rel in ("gradle/libs.versions.toml", "libs.versions.toml"):
        toml_p = repo / toml_rel
        if not toml_p.is_file():
            continue
        try:
            txt = toml_p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        versions_map: dict[str, str] = {}
        section = ""
        for raw_line in txt.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().lower()
                continue
            if section == "versions" and "=" in line:
                k, val = line.split("=", 1)
                v_clean = val.strip().strip("\"'")
                if k.strip() and v_clean:
                    versions_map[k.strip()] = v_clean
            elif section == "libraries" and "=" in line:
                _, rhs = line.split("=", 1)
                rhs = rhs.strip()
                if rhs.startswith(("\"", "'")):
                    parts = rhs.strip("\"'").split(":")
                    if len(parts) == 3:
                        _record(parts[0], parts[1], parts[2])
                elif rhs.startswith("{"):
                    m_mod = re.search(r"""module\s*=\s*['"]([^'"]+)['"]""", rhs)
                    m_grp = re.search(r"""group\s*=\s*['"]([^'"]+)['"]""", rhs)
                    m_nam = re.search(r"""name\s*=\s*['"]([^'"]+)['"]""", rhs)
                    m_vref = re.search(r"""version\.ref\s*=\s*['"]([^'"]+)['"]""", rhs)
                    m_ver = re.search(r"""(?<!\.)version\s*=\s*['"]([^'"]+)['"]""", rhs)
                    grp, art = "", ""
                    if m_mod and ":" in m_mod.group(1):
                        grp, art = m_mod.group(1).split(":", 1)
                    elif m_grp and m_nam:
                        grp, art = m_grp.group(1), m_nam.group(1)
                    ver = ""
                    if m_vref:
                        ver = versions_map.get(m_vref.group(1), "")
                    elif m_ver:
                        ver = m_ver.group(1)
                    if grp and art and ver:
                        _record(grp, art, ver)

    # 2. Root and module `build.gradle` / `build.gradle.kts`
    gradle_files: list[Path] = []
    seen_gf: set[Path] = set()
    skip_dirs = {"build", ".gradle", ".git", ".idea", "node_modules", ".agents"}

    def _add_gf(p: Path) -> None:
        if len(gradle_files) >= 120 or not p.is_file() or p.name not in {"build.gradle", "build.gradle.kts"}:
            return
        try:
            rel_parts = p.relative_to(repo).parts
        except ValueError:
            rel_parts = p.parts
        if any(part in skip_dirs for part in rel_parts):
            return
        if p not in seen_gf:
            seen_gf.add(p)
            gradle_files.append(p)

    for root_gf in ("build.gradle", "build.gradle.kts"):
        _add_gf(repo / root_gf)
    for pattern in ("*/build.gradle*", "*/*/build.gradle*", "*/*/*/build.gradle*"):
        for sub_gf in sorted(repo.glob(pattern)):
            _add_gf(sub_gf)
            if len(gradle_files) >= 120:
                break

    vars_map: dict[str, str] = {}
    file_texts: list[str] = []
    for gf in gradle_files:
        try:
            gtxt = gf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        file_texts.append(gtxt)
        for vm in _GROOVY_OR_KTS_VAR_RE.finditer(gtxt):
            vars_map[vm.group(1)] = vm.group(2)

    for gtxt in file_texts:
        for cm in _COORD_LITERAL_RE.finditer(gtxt):
            grp, art, raw_v = cm.group(1), cm.group(2), cm.group(3)
            if raw_v.startswith("$"):
                v_key = raw_v.lstrip("$").strip("{}")
                raw_v = vars_map.get(v_key, "")
            if raw_v:
                _record(grp, art, raw_v)
    return found


def _semver_sort_key(ver: str) -> tuple[int, ...]:
    nums = [int(x) for x in re.findall(r"\d+", ver)[:5]]
    while len(nums) < 5:
        nums.append(0)
    # Prefer stable releases over alpha/beta/rc when numeric prefix is equal
    is_stable = 0 if any(tag in ver.lower() for tag in ("alpha", "beta", "rc", "snapshot", "dev")) else 1
    return (*nums, is_stable)


def resolve_dependency_coordinate(
    repo: Path,
    raw_target: str,
    *,
    extra_cache_dirs: list[Path] | None = None,
    offline: bool = False,
    maven_repos: list[str] | None = None,
) -> tuple[str, str, str]:
    cleaned = str(raw_target or "").strip().strip("\"'")
    if not cleaned:
        raise ValidationError("MISSING_DEPENDENCY_TARGET: Pass `<group:artifact[:version]>` or `<artifact>`.")

    parts = [p.strip() for p in cleaned.split(":") if p.strip()]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]

    declared, versionless, declared_boms = _parse_repo_catalog_and_boms(repo)
    cache_roots = _discover_gradle_files21_roots(repo, extra_cache_dirs=extra_cache_dirs)

    def _find_cached_version(grp_q: str, art_q: str) -> str:
        cached_vers: list[str] = []
        variants_q = [art_q] if art_q.endswith(("-android", "-jvm")) else [art_q, f"{art_q}-android", f"{art_q}-jvm"]
        for croot in cache_roots:
            for v_art in variants_q:
                art_dir = croot / grp_q / v_art
                if art_dir.is_dir():
                    try:
                        cached_vers.extend(d.name for d in art_dir.iterdir() if d.is_dir())
                    except OSError:
                        pass
        if cached_vers:
            cached_vers.sort(key=_semver_sort_key, reverse=True)
            return cached_vers[0]
        return ""

    if len(parts) == 2:
        grp, art = parts[0], parts[1]
        matching_vers = [v for g, a, v in declared if g == grp and a == art]
        if matching_vers:
            matching_vers.sort(key=_semver_sort_key, reverse=True)
            return grp, art, matching_vers[0]
        bom_ver = _resolve_version_from_boms(
            repo, grp, art, declared_boms, cache_roots, offline=offline, maven_repos=maven_repos
        )
        if bom_ver:
            return grp, art, bom_ver
        c_ver = _find_cached_version(grp, art)
        if c_ver:
            return grp, art, c_ver
        raise ValidationError(
            f"DEPENDENCY_VERSION_NOT_FOUND: Could not auto-resolve version for `{grp}:{art}` from `build.gradle*`, "
            "`libs.versions.toml` (including declared BOMs), or local Gradle cache. Pass `<group>:<artifact>:<version>`."
        )

    art_only = parts[0]
    exact_decl = [(g, a, v) for g, a, v in declared if a == art_only]
    if not exact_decl:
        exact_decl = [(g, a, v) for g, a, v in declared if art_only.lower() in a.lower()]
    if exact_decl:
        exact_decl.sort(key=lambda item: _semver_sort_key(item[2]), reverse=True)
        return exact_decl[0]

    # Check versionless catalog entries (BOM-managed libraries such as `material3` or `firebase-auth`)
    # Prefer the repository's declared BOM version before falling back to global `~/.gradle` caches.
    vless_matches = [(g, a) for g, a in versionless if a == art_only] or [
        (g, a) for g, a in versionless if art_only.lower() in a.lower()
    ]
    for vl_grp, vl_art in vless_matches:
        bom_ver = _resolve_version_from_boms(
            repo, vl_grp, vl_art, declared_boms, cache_roots, offline=offline, maven_repos=maven_repos
        )
        if bom_ver:
            return vl_grp, vl_art, bom_ver
        c_ver = _find_cached_version(vl_grp, vl_art)
        if c_ver:
            return vl_grp, vl_art, c_ver

    cached_matches: list[tuple[str, str, str]] = []
    for croot in cache_roots:
        try:
            for grp_dir in croot.iterdir():
                if not grp_dir.is_dir():
                    continue
                for v_art in ([art_only] if art_only.endswith(("-android", "-jvm")) else [art_only, f"{art_only}-android", f"{art_only}-jvm"]):
                    cand_art = grp_dir / v_art
                    if cand_art.is_dir():
                        for v_dir in cand_art.iterdir():
                            if v_dir.is_dir():
                                cached_matches.append((grp_dir.name, art_only, v_dir.name))
        except OSError:
            continue
    if cached_matches:
        cached_matches.sort(key=lambda item: _semver_sort_key(item[2]), reverse=True)
        return cached_matches[0]

    raise ValidationError(
        f"DEPENDENCY_NOT_FOUND: Could not resolve `{art_only}` in project Gradle files or local Gradle cache. "
        "Pass the full Maven coordinate `<group>:<artifact>:<version>`."
    )


def _configured_maven_repos(repo: Path, custom_repos: list[str] | None = None) -> list[str]:
    if custom_repos:
        return [r.rstrip("/") for r in custom_repos if r.strip()]
    repos = list(PUBLIC_MAVEN_REPOS)
    for rel in ("settings.gradle", "settings.gradle.kts", "build.gradle", "build.gradle.kts"):
        fp = repo / rel
        if fp.is_file():
            try:
                txt = fp.read_text(encoding="utf-8", errors="ignore")
                if "jitpack.io" in txt and JITPACK_REPO not in repos:
                    repos.append(JITPACK_REPO)
            except OSError:
                pass
    return repos


def _has_meaningful_sources(jar_path: Path) -> bool:
    if not jar_path.is_file():
        return False
    try:
        if jar_path.stat().st_size < 32:
            return False
        with zipfile.ZipFile(jar_path, "r") as zf:
            return any(n.endswith((".kt", ".java")) for n in zf.namelist())
    except (OSError, zipfile.BadZipFile):
        return False


def _locate_local_artifact(
    repo: Path,
    group: str,
    artifact: str,
    version: str,
    *,
    sources: bool,
    extra_cache_dirs: list[Path] | None = None,
) -> Path | None:
    variants = [artifact]
    if not artifact.endswith(("-android", "-jvm")):
        variants.extend([f"{artifact}-android", f"{artifact}-jvm"])

    if sources:
        local_cache = _dep_sources_cache_dir(repo)
        for var_art in variants:
            safe_name = f"{group}__{var_art}__{version}-sources.jar".replace(":", "_")
            cached_p = local_cache / safe_name
            if _has_meaningful_sources(cached_p):
                return cached_p

    for croot in _discover_gradle_files21_roots(repo, extra_cache_dirs=extra_cache_dirs):
        for var_art in variants:
            ver_dir = croot / group / var_art / version
            if not ver_dir.is_dir():
                continue
            try:
                if sources:
                    for cand in sorted(ver_dir.rglob(f"{var_art}-{version}-sources.jar")):
                        if _has_meaningful_sources(cand):
                            return cand
                else:
                    for ext in (".aar", ".jar"):
                        for cand in sorted(ver_dir.rglob(f"{var_art}-{version}{ext}")):
                            if not cand.name.endswith(("-sources.jar", "-javadoc.jar")) and cand.is_file():
                                return cand
            except OSError:
                continue
    return None


def _download_maven_artifact(
    repo: Path,
    group: str,
    artifact: str,
    version: str,
    *,
    sources: bool,
    maven_repos: list[str] | None = None,
) -> tuple[Path | None, str]:
    repos = _configured_maven_repos(repo, custom_repos=maven_repos)
    variants = [artifact]
    if not artifact.endswith(("-android", "-jvm")):
        variants.extend([f"{artifact}-android", f"{artifact}-jvm"])

    grp_path = group.replace(".", "/")
    dest_dir = _dep_sources_cache_dir(repo)
    dest_dir.mkdir(parents=True, exist_ok=True)

    suffixes = ("-sources.jar",) if sources else (".aar", ".jar")
    for base_url in repos:
        for var_art in variants:
            for sfx in suffixes:
                file_name = f"{var_art}-{version}{sfx}"
                url = f"{base_url}/{grp_path}/{var_art}/{version}/{file_name}"
                req = urllib.request.Request(url, headers={"User-Agent": "android-agent-harness-dep-inspect/1.0"})
                try:
                    with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT_SECONDS) as resp:
                        resp_status = getattr(resp, "status", None)
                        if resp_status is not None and int(resp_status) != 200:
                            continue
                        data = resp.read(MAX_DOWNLOAD_BYTES + 1)
                        if len(data) > MAX_DOWNLOAD_BYTES:
                            continue
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
                    continue
                safe_local = f"{group}__{var_art}__{version}{sfx}".replace(":", "_")
                out_path = dest_dir / safe_local
                tmp_path = dest_dir / f".tmp-{os.getpid()}-{safe_local}"
                try:
                    tmp_path.write_bytes(data)
                    tmp_path.replace(out_path)
                except OSError:
                    tmp_path.unlink(missing_ok=True)
                    continue
                if sources and not _has_meaningful_sources(out_path):
                    out_path.unlink(missing_ok=True)
                    continue
                return out_path, url
    return None, ""


def _compact_source_text(raw_text: str, *, keep_imports: bool = False) -> str:
    """Strip leading license comments and `import ...` blocks to maximize signal per token."""
    lines = raw_text.replace("\r\n", "\n").splitlines()
    out: list[str] = []
    in_header_comment = True
    for line in lines:
        stripped = line.strip()
        if in_header_comment:
            if not stripped or stripped.startswith(("//", "/*", "*", "*/")):
                continue
            in_header_comment = False
        if not keep_imports and (stripped.startswith("import ") or stripped == "import"):
            continue
        out.append(line)
    # Collapse 3+ consecutive blank lines
    cleaned = "\n".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _extract_focused_excerpt(compacted: str, query_tokens: list[str], budget: int) -> str:
    if len(compacted) <= budget or not query_tokens:
        return compacted[:budget]
    lines = compacted.splitlines()
    pkg_line = next((ln for ln in lines[:8] if ln.strip().startswith("package ")), "")
    hit_indices: list[int] = []
    for idx, ln in enumerate(lines):
        low = ln.lower()
        if any(qt in low for qt in query_tokens):
            hit_indices.append(idx)
    if not hit_indices:
        return compacted[:budget]

    windows: list[tuple[int, int]] = []
    for h in hit_indices[:12]:
        start = max(0, h - 8)
        end = min(len(lines), h + 28)
        if windows and start <= windows[-1][1] + 2:
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))

    chunks: list[str] = [pkg_line] if pkg_line else []
    used = len(pkg_line) + 2
    for w_start, w_end in windows:
        snippet = "\n".join(f"{ln_no + 1}: {lines[ln_no]}" for ln_no in range(w_start, w_end))
        if used + len(snippet) + 20 > budget and len(chunks) > 1:
            break
        chunks.append(snippet)
        used += len(snippet) + 2
    joined = "\n...\n".join(chunks)
    return joined[:budget]


def inspect_sources_jar(
    jar_path: Path,
    *,
    query: str = "",
    entry_filter: str = "",
    keep_imports: bool = False,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    budget = max(800, min(int(max_chars or DEFAULT_MAX_CHARS), HARD_MAX_CHARS))
    q_clean = str(query or "").strip().lower()
    q_tokens = [t for t in re.split(r"[\s,;|]+", q_clean) if t]
    f_clean = str(entry_filter or "").strip().replace("\\", "/").lstrip("/").lower()

    with zipfile.ZipFile(jar_path, "r") as zf:
        src_entries = [
            n for n in zf.namelist()
            if n.endswith((".kt", ".java")) and not n.endswith("package-info.java")
        ]
        if f_clean:
            matched_files = [n for n in src_entries if n.lower().endswith(f_clean) or f_clean in n.lower()]
            excerpts: list[dict[str, Any]] = []
            rem = budget
            for entry in matched_files[:5]:
                if rem <= 120:
                    break
                raw = zf.read(entry).decode("utf-8", errors="replace")
                comp = _compact_source_text(raw, keep_imports=keep_imports)
                piece = _extract_focused_excerpt(comp, q_tokens, min(rem, budget))
                excerpts.append({
                    "entry": entry,
                    "truncated": len(comp) > len(piece),
                    "source": piece,
                })
                rem -= len(piece)
            return {
                "mode": "sources_jar",
                "total_source_files": len(src_entries),
                "matched_count": len(matched_files),
                "matches": excerpts,
            }

        if not q_tokens:
            # Summary mode: list packages and top source files without dumping bodies
            packages: set[str] = set()
            sample_entries: list[str] = []
            for entry in sorted(src_entries):
                if "/" in entry:
                    packages.add(entry.rsplit("/", 1)[0].replace("/", "."))
                if len(sample_entries) < 50:
                    sample_entries.append(entry)
            return {
                "mode": "sources_jar_index",
                "total_source_files": len(src_entries),
                "packages": sorted(packages)[:40],
                "sample_files": sample_entries,
            }

        scored: list[tuple[int, str, str]] = []
        for entry in src_entries:
            entry_low = entry.lower()
            stem_low = Path(entry).stem.lower()
            try:
                raw = zf.read(entry).decode("utf-8", errors="replace")
            except (OSError, KeyError):
                continue
            raw_low = raw.lower()
            if not any(qt in entry_low or qt in raw_low for qt in q_tokens):
                continue

            score = 0
            for qt in q_tokens:
                if stem_low == qt:
                    score += 120
                elif qt in stem_low:
                    score += 65
                elif qt in entry_low:
                    score += 35
                if qt in raw_low:
                    score += 15
            # Boost public declarations matching query tokens and lightly deprioritize purely internal files
            has_public_decl = False
            has_internal_only = "internal class " in raw_low or "internal fun " in raw_low or "internal interface " in raw_low
            for ln in raw.splitlines():
                m_decl = _DECL_LINE_RE.match(ln)
                if m_decl:
                    sym = m_decl.group(1).strip("`").lower()
                    if any(qt in sym for qt in q_tokens):
                        score += 55
                        if "internal " not in ln and "private " not in ln:
                            has_public_decl = True
            if has_public_decl:
                score += 30
            elif has_internal_only:
                score -= 10
            scored.append((score, entry, raw))

        scored.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
        excerpts = []
        rem = budget
        for score, entry, raw in scored[:8]:
            if rem <= 200:
                break
            comp = _compact_source_text(raw, keep_imports=keep_imports)
            per_file_cap = min(rem, max(1200, budget // max(1, min(len(scored), 3))))
            piece = _extract_focused_excerpt(comp, q_tokens, per_file_cap)
            excerpts.append({
                "entry": entry,
                "score": score,
                "truncated": len(comp) > len(piece),
                "source": piece,
            })
            rem -= len(piece)
        return {
            "mode": "sources_jar",
            "total_source_files": len(src_entries),
            "matched_count": len(scored),
            "matches": excerpts,
        }


def _resolve_javap_binary() -> str:
    env_jh = os.environ.get("JAVA_HOME", "").strip()
    if env_jh:
        for exe in ("javap.exe", "javap"):
            cand = Path(env_jh) / "bin" / exe
            if cand.is_file():
                return str(cand)
    found = shutil.which("javap")
    return found or ""


def inspect_binary_archive(
    archive_path: Path,
    *,
    query: str = "",
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """Fallback for closed-source `.aar`/`.jar` packages without `-sources.jar`: extract clean `javap -public` signatures."""
    budget = max(800, min(int(max_chars or DEFAULT_MAX_CHARS), HARD_MAX_CHARS))
    q_clean = str(query or "").strip().lower()
    q_tokens = [t for t in re.split(r"[\s,;|]+", q_clean) if t]

    with tempfile.TemporaryDirectory(prefix="harness-dep-bin-") as td:
        tmp_dir = Path(td)
        classes_jar = archive_path
        if archive_path.suffix.lower() == ".aar":
            with zipfile.ZipFile(archive_path, "r") as aar_zf:
                if "classes.jar" not in aar_zf.namelist():
                    return {"mode": "binary_classes", "matched_count": 0, "classes": [], "signatures": ""}
                classes_jar = tmp_dir / "classes.jar"
                classes_jar.write_bytes(aar_zf.read("classes.jar"))

        with zipfile.ZipFile(classes_jar, "r") as czf:
            class_entries = [
                n for n in czf.namelist()
                if n.endswith(".class")
                and not n.endswith(("module-info.class", "package-info.class"))
                and not _SYNTHETIC_CLASS_NOISE_RE.search(n)
            ]

        fqcns = [n[:-6].replace("/", ".") for n in class_entries]
        if q_tokens:
            matched = [
                c for c in fqcns
                if any(qt in c.lower() for qt in q_tokens)
            ]
        else:
            matched = [c for c in fqcns if "$" not in c]

        matched.sort(key=lambda c: ("$" in c, len(c), c))
        top_classes = matched[:12]
        signatures = ""
        javap_bin = _resolve_javap_binary()
        if javap_bin and top_classes:
            try:
                proc = subprocess.run(
                    [javap_bin, "-cp", str(classes_jar), "-public", *top_classes],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    signatures = proc.stdout.strip()[:budget]
            except (OSError, subprocess.SubprocessError):
                signatures = ""

        return {
            "mode": "binary_public_signatures",
            "total_classes": len(fqcns),
            "matched_count": len(matched),
            "classes": top_classes,
            "signatures": signatures,
        }


def inspect_dependency(
    repo: Path,
    target: str,
    *,
    query: str = "",
    entry_filter: str = "",
    offline: bool = False,
    keep_imports: bool = False,
    max_chars: int = DEFAULT_MAX_CHARS,
    extra_cache_dirs: list[Path] | None = None,
    maven_repos: list[str] | None = None,
) -> dict[str, Any]:
    repo = Path(repo).resolve()
    group, artifact, version = resolve_dependency_coordinate(
        repo,
        target,
        extra_cache_dirs=extra_cache_dirs,
        offline=offline,
        maven_repos=maven_repos,
    )

    src_jar = _locate_local_artifact(
        repo, group, artifact, version, sources=True, extra_cache_dirs=extra_cache_dirs
    )
    fetched_url = ""
    if src_jar is None and not offline:
        src_jar, fetched_url = _download_maven_artifact(
            repo, group, artifact, version, sources=True, maven_repos=maven_repos
        )

    if src_jar is not None and src_jar.is_file():
        payload = inspect_sources_jar(
            src_jar,
            query=query,
            entry_filter=entry_filter,
            keep_imports=keep_imports,
            max_chars=max_chars,
        )
        return {
            "status": "OK",
            "coordinate": f"{group}:{artifact}:{version}",
            "artifact_path": str(src_jar),
            "downloaded_on_demand": bool(fetched_url),
            **({"downloaded_from": fetched_url} if fetched_url else {}),
            **payload,
        }

    bin_archive = _locate_local_artifact(
        repo, group, artifact, version, sources=False, extra_cache_dirs=extra_cache_dirs
    )
    if bin_archive is None and not offline:
        bin_archive, fetched_url = _download_maven_artifact(
            repo, group, artifact, version, sources=False, maven_repos=maven_repos
        )

    if bin_archive is not None and bin_archive.is_file():
        payload = inspect_binary_archive(bin_archive, query=query, max_chars=max_chars)
        return {
            "status": "OK",
            "coordinate": f"{group}:{artifact}:{version}",
            "artifact_path": str(bin_archive),
            "downloaded_on_demand": bool(fetched_url),
            "note": "No `-sources.jar` published for this coordinate; extracted clean public class signatures.",
            **payload,
        }

    offline_hint = " (offline mode enabled)" if offline else ""
    raise ValidationError(
        f"DEPENDENCY_ARTIFACT_UNAVAILABLE: Could not locate or fetch `-sources.jar` or `.aar`/`.jar` for "
        f"`{group}:{artifact}:{version}`{offline_hint}. Verify the Maven coordinate/version or run `python .agents/harness.py compile` if the artifact lives in a private authenticated Maven repository."
    )


def _format_human_output(report: dict[str, Any]) -> str:
    lines = [
        f"[dep-inspect] {report['coordinate']} (mode={report['mode']}, downloaded_on_demand={report.get('downloaded_on_demand', False)})",
        f"  artifact: {report['artifact_path']}",
    ]
    if report.get("note"):
        lines.append(f"  note: {report['note']}")
    mode = report.get("mode")
    if mode == "sources_jar_index":
        lines.append(f"  total_source_files: {report.get('total_source_files', 0)}")
        for pkg in report.get("packages") or []:
            lines.append(f"    package {pkg}")
        for sf in (report.get("sample_files") or [])[:25]:
            lines.append(f"    - {sf}")
    elif mode == "sources_jar":
        lines.append(f"  matched_files: {report.get('matched_count', 0)} (showing {len(report.get('matches') or [])})")
        for item in report.get("matches") or []:
            trunc = " [truncated]" if item.get("truncated") else ""
            lines.append(f"\n--- {item['entry']}{trunc} ---")
            lines.append(str(item.get("source") or ""))
    else:
        lines.append(f"  matched_classes: {report.get('matched_count', 0)}")
        if report.get("signatures"):
            lines.append("")
            lines.append(str(report["signatures"]))
        else:
            for cls_name in report.get("classes") or []:
                lines.append(f"    - {cls_name}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dep_inspect.py",
        description=(
            "Inspect third-party Gradle/Maven library Kotlin/Java sources (`-sources.jar`, auto-fetched even before "
            "Android Studio Sync) or clean `javap -public` signatures without raw bytecode bloat."
        ),
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="",
        help="Maven coordinate `<group:artifact[:version]>` or `<artifact>` (version auto-resolved from project Gradle files).",
    )
    parser.add_argument("--coord", default="", help="Explicit Maven coordinate alias for positional `target`.")
    parser.add_argument("--repo", default=".", help="Android repository root.")
    parser.add_argument("--query", "-q", default="", help="Class, method, annotation, or keyword to locate inside the library.")
    parser.add_argument("--file", default="", help="Exact or suffix source file path inside `-sources.jar` (e.g. `CheckpointParams.kt`).")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help=f"Character budget (default {DEFAULT_MAX_CHARS}, max {HARD_MAX_CHARS}).")
    parser.add_argument("--keep-imports", action="store_true", help="Retain `import` statements in extracted source excerpts.")
    parser.add_argument("--offline", action="store_true", help="Inspect local Gradle/harness caches only without network fetch.")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    target = str(args.coord or args.target or "").strip()
    repo = Path(args.repo or ".").resolve()
    configure_utf8_output()
    try:
        report = inspect_dependency(
            repo,
            target,
            query=args.query,
            entry_filter=args.file,
            offline=bool(args.offline),
            keep_imports=bool(args.keep_imports),
            max_chars=int(args.max_chars or DEFAULT_MAX_CHARS),
        )
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(_format_human_output(report))
        return 0
    except ValidationError as exc:
        if args.json:
            print(json.dumps({"status": "ERROR", "error": str(exc)}, indent=2, ensure_ascii=False))
        else:
            print(f"[FAIL] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
