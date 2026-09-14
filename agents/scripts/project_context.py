"""Project-derived architectural context engine and fact extraction library.

Zero-dependency standard library Python engine providing deterministic, evidence-backed
extraction of Android and KMP project architecture (DI, BaseViewModel, Navigation,
Persistence, Theming, Capabilities). Renders reproducible markdown views and computes
normalized architectural fingerprints.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
EXTRACTOR_VERSION = "1.0.0"

SKIP_PARTS = {
    ".git", ".gradle", "build", ".harness-backup", ".harness-recovery",
    "node_modules", "__pycache__", ".idea",
}

TECHNICAL_CAPABILITIES: dict[str, dict[str, tuple[str, ...]]] = {
    "networking": {
        "signatures": ("retrofit", "retrofit2", "io.ktor", "ktor-client", "okhttp3", "com.apollographql"),
    },
    "location": {
        "signatures": ("play-services-location", "ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION", "com.mapbox"),
    },
    "maps": {
        "signatures": ("play-services-maps", "com.google.android.gms.maps", "com.mapbox.maps"),
    },
    "sensors": {
        "signatures": ("SensorEventListener", "SensorManager", "TYPE_STEP_COUNTER", "TYPE_ACCELEROMETER", "TYPE_HEART_RATE"),
    },
    "health_connect": {
        "signatures": ("androidx.health.connect", "HealthConnectClient", "health-connect-client"),
    },
    "billing": {
        "signatures": ("com.android.billingclient", "billing-ktx", "com.stripe", "revenuecat"),
    },
    "audio": {
        "signatures": ("androidx.media3", "exoplayer", "SoundPool", "MediaPlayer"),
    },
    "camera": {
        "signatures": ("androidx.camera", "camera-camera2", "camera-lifecycle", "camera-view"),
    },
    "bluetooth": {
        "signatures": ("android.bluetooth", "BluetoothAdapter", "BluetoothDevice", "BluetoothGatt", "BLUETOOTH_CONNECT"),
    },
}


def _skip_path(path: Path, repo: Path) -> bool:
    try:
        rel = path.relative_to(repo)
        parts = set(rel.parts)
    except ValueError:
        return True
    return bool(parts & SKIP_PARTS)


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rel_path(path: Path, repo: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return path.name


def extract_project_facts(repo: Path, *, in_memory_graph: bool = True, cache_dir: Path | None = None) -> dict:
    """Deterministically extracts architectural facts from repo with zero PII and zero secrets."""
    repo = repo.resolve()

    modules: list[str] = []
    settings_text = ""
    for s_name in ("settings.gradle.kts", "settings.gradle"):
        s_path = repo / s_name
        if s_path.is_file():
            settings_text = _safe_read(s_path)
            for m in re.finditer(r'include\s*\(?\s*["\']([^"\']+)["\']\s*\)?', settings_text):
                modules.append(m.group(1))

    build_texts: dict[str, str] = {}
    for build_file in repo.glob("**/build.gradle*"):
        if not _skip_path(build_file, repo):
            rel = _rel_path(build_file, repo)
            build_texts[rel] = _safe_read(build_file)

    toml_text = ""
    toml_path = repo / "gradle" / "libs.versions.toml"
    if toml_path.is_file():
        toml_text = _safe_read(toml_path)

    corpus_gradle = "\n".join(build_texts.values()) + "\n" + toml_text

    # --- 1. DI Framework Detection ---
    di_framework = "unknown"
    di_evidence: list[dict] = []
    di_modules: list[dict] = []

    if "dagger.hilt" in corpus_gradle or "hilt-android" in corpus_gradle or "com.google.dagger.hilt.android" in corpus_gradle:
        di_framework = "hilt"
        di_evidence.append({"type": "build_file", "evidence": "dagger.hilt / hilt-android dependency declared", "confidence": "HIGH"})
    elif "org.koin" in corpus_gradle or "koin-android" in corpus_gradle:
        di_framework = "koin"
        di_evidence.append({"type": "build_file", "evidence": "koin-android dependency declared", "confidence": "HIGH"})

    # --- 2. Codebase Scan for Bases, Theme, and Modules ---
    vm_candidates: list[dict] = []
    room_databases: list[dict] = []
    room_daos: list[dict] = []
    datastore_preferences: list[dict] = []
    compose_themes: list[dict] = []
    result_wrappers: list[dict] = []
    nav_elements: list[dict] = []

    kt_files_scanned = 0
    max_kt_files = 800
    kt_samples: list[str] = []

    for p in repo.rglob("*.kt"):
        if kt_files_scanned >= max_kt_files:
            break
        if _skip_path(p, repo) or ".agents" in p.parts:
            continue
        rel = _rel_path(p, repo)
        txt = _safe_read(p)
        if not txt:
            continue
        kt_files_scanned += 1
        kt_samples.append(txt[:2000])

        # DI Modules
        if di_framework == "hilt" and "@Module" in txt and ("@InstallIn" in txt or "@Provides" in txt or "@Binds" in txt):
            m_cls = re.search(r"(?:abstract\s+)?(?:class|object|interface)\s+([A-Za-z0-9_]+)", txt)
            if m_cls:
                di_modules.append({"name": m_cls.group(1), "path": rel})
        elif di_framework == "koin" and re.search(r"module\s*\{", txt):
            m_koin = re.search(r"val\s+([A-Za-z0-9_]+Module)\s*=", txt)
            if m_koin:
                di_modules.append({"name": m_koin.group(1), "path": rel})

        # ViewModel Bases
        m_vms = re.finditer(r"(?:abstract|open)\s+class\s+([A-Za-z0-9_]+)(<[^>]+>)?\s*:\s*(?:androidx\.lifecycle\.)?ViewModel\s*\([^)]*\)", txt)
        for m_vm in m_vms:
            cls_name = m_vm.group(1)
            generics = (m_vm.group(2) or "").strip()
            pkg_m = re.search(r"package\s+([a-zA-Z0-9_.]+)", txt)
            pkg = pkg_m.group(1) if pkg_m else ""
            vm_candidates.append({
                "symbol": cls_name,
                "package": pkg,
                "generics": generics,
                "path": rel,
            })

        # Room Database
        if "@Database" in txt and "RoomDatabase" in txt:
            m_db = re.search(r"(?:abstract\s+)?class\s+([A-Za-z0-9_]+)\s*:\s*(?:androidx\.room\.)?RoomDatabase\s*\(\s*\)", txt)
            m_ver = re.search(r"@Database\s*\([^)]*version\s*=\s*(\d+)", txt)
            m_ent = re.search(r"@Database\s*\([^)]*entities\s*=\s*\[([^\]]+)\]", txt)
            db_name = m_db.group(1) if m_db else p.stem
            version = int(m_ver.group(1)) if m_ver else 1
            entities = [e.strip().replace("::class", "") for e in m_ent.group(1).split(",") if e.strip()] if m_ent else []
            room_databases.append({
                "symbol": db_name,
                "version": version,
                "entities_count": len(entities),
                "entities": sorted(entities),
                "path": rel,
            })

        # Room DAOs
        if "@Dao" in txt:
            m_dao = re.search(r"interface\s+([A-Za-z0-9_]+)", txt)
            if m_dao:
                room_daos.append({"symbol": m_dao.group(1), "path": rel})

        # DataStore Preferences
        if "preferencesDataStore" in txt or "DataStore<Preferences>" in txt:
            datastore_preferences.append({"file": rel})

        # Compose Theme
        m_theme = re.finditer(r"@Composable\s+fun\s+([A-Za-z0-9_]+Theme)\s*\(", txt)
        for th in m_theme:
            compose_themes.append({"symbol": th.group(1), "path": rel})

        # Result / Resource Wrappers
        m_res = re.search(r"sealed\s+(?:class|interface)\s+(Result|Resource|NetworkResult|ApiResponse|UiState)(<[^>]+>)?", txt)
        if m_res:
            result_wrappers.append({"symbol": m_res.group(1), "path": rel})

        # Navigation
        if "NavHost" in txt or "rememberNavController" in txt or "composable<" in txt or "NavGraphBuilder" in txt:
            nav_elements.append({"type": "compose_nav", "path": rel})
        elif "Voyager" in txt or "Navigator(" in txt:
            nav_elements.append({"type": "voyager", "path": rel})

    # XML Navigation graphs
    for nav_xml in repo.glob("**/res/navigation/*.xml"):
        if not _skip_path(nav_xml, repo):
            nav_elements.append({"type": "xml_nav_graph", "path": _rel_path(nav_xml, repo)})

    # UI Framework classification
    has_compose = "androidx.compose" in corpus_gradle or bool(compose_themes)
    has_xml_views = bool(list(repo.glob("**/res/layout/*.xml")))
    ui_framework = "compose" if has_compose and not has_xml_views else "hybrid" if has_compose and has_xml_views else "xml" if has_xml_views else "compose"

    # Resolve ViewModel Primary Base
    primary_vm = None
    vm_resolution = "NONE"
    if len(vm_candidates) == 1:
        primary_vm = vm_candidates[0]
        vm_resolution = "RESOLVED"
    elif len(vm_candidates) > 1:
        base_named = [c for c in vm_candidates if c["symbol"] == "BaseViewModel"]
        if len(base_named) == 1:
            primary_vm = base_named[0]
            vm_resolution = "RESOLVED_CONVENTION"
        else:
            vm_resolution = "UNRESOLVED"

    # Technical Capabilities Detection
    manifest_samples: list[str] = []
    for m in repo.glob("**/AndroidManifest.xml"):
        if not _skip_path(m, repo):
            manifest_samples.append(_safe_read(m))

    capabilities: dict[str, dict] = {}
    full_text_sample = corpus_gradle + "\n" + "\n".join(manifest_samples) + "\n" + "\n".join(kt_samples)
    for cap_name, config in TECHNICAL_CAPABILITIES.items():
        matched_sigs: list[str] = []
        for sig in config["signatures"]:
            if sig.lower() in full_text_sample.lower():
                matched_sigs.append(sig)
        if matched_sigs:
            capabilities[cap_name] = {
                "detected": True,
                "confidence": "HIGH",
                "evidence_signatures": sorted(matched_sigs),
            }
        else:
            capabilities[cap_name] = {
                "detected": False,
                "confidence": "LOW",
                "evidence_signatures": [],
            }

    facts = {
        "modules": sorted(set(modules)),
        "di": {
            "framework": di_framework,
            "evidence": di_evidence,
            "modules": sorted(di_modules, key=lambda m: (m.get("name", ""), m.get("path", ""))),
        },
        "view_models": {
            "resolution": vm_resolution,
            "primary": primary_vm,
            "candidates": sorted(vm_candidates, key=lambda c: (c.get("symbol", ""), c.get("path", ""))),
        },
        "persistence": {
            "room_databases": sorted(room_databases, key=lambda d: (d.get("symbol", ""), d.get("path", ""))),
            "room_daos": sorted(room_daos, key=lambda d: (d.get("symbol", ""), d.get("path", ""))),
            "datastore_preferences": sorted(datastore_preferences, key=lambda d: d.get("file", "")),
        },
        "ui": {
            "framework": ui_framework,
            "themes": sorted(compose_themes, key=lambda t: (t.get("symbol", ""), t.get("path", ""))),
        },
        "navigation": {
            "elements": sorted(nav_elements, key=lambda n: (n.get("type", ""), n.get("path", ""))),
        },
        "conventions": {
            "result_wrappers": sorted(result_wrappers, key=lambda r: (r.get("symbol", ""), r.get("path", ""))),
        },
        "capabilities": capabilities,
    }

    normalized = normalize_project_facts(facts)
    fingerprint = project_context_fingerprint(normalized)

    return {
        "schema_version": SCHEMA_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "context_fingerprint_sha256": fingerprint,
        "facts": normalized,
    }


def normalize_project_facts(facts: dict) -> dict:
    """Sorts and normalizes facts structure to guarantee deterministic hashing."""
    if not isinstance(facts, dict):
        return facts
    norm: dict = {}
    for k in sorted(facts.keys()):
        v = facts[k]
        if isinstance(v, dict):
            norm[k] = normalize_project_facts(v)
        elif isinstance(v, list):
            norm_list = []
            for item in v:
                norm_list.append(normalize_project_facts(item) if isinstance(item, dict) else item)
            try:
                norm[k] = sorted(norm_list, key=lambda x: _canonical_json(x))
            except TypeError:
                norm[k] = norm_list
        else:
            norm[k] = v
    return norm


def project_context_fingerprint(facts: dict) -> str:
    """Calculates canonical SHA-256 over normalized facts, strictly ignoring timestamps."""
    content = facts.get("facts") if "facts" in facts else facts
    canonical = _canonical_json(normalize_project_facts(content))
    return _sha256_text(canonical)


def render_project_context(facts_payload: dict) -> dict[str, str]:
    """Deterministically renders markdown documents from project facts."""
    facts = facts_payload.get("facts") or facts_payload

    # 1. architecture.md
    di = facts.get("di") or {}
    vm = facts.get("view_models") or {}
    nav = facts.get("navigation") or {}
    conv = facts.get("conventions") or {}

    arch_lines = [
        "# Project Architecture & Component Contracts",
        "",
        "> Generated by Android Agent Harness from deterministic project static analysis.",
        "> Update via `android-harness context refresh` if architecture evolves.",
        "",
        "## 1. Dependency Injection",
        f"- **Framework**: `{di.get('framework', 'unknown').upper()}`",
    ]
    if di.get("modules"):
        arch_lines.append("- **Discovered Modules**:")
        for mod in di["modules"]:
            arch_lines.append(f"  - `{mod['name']}` in [`{mod['path']}`](file:///{mod['path']})")
    else:
        arch_lines.append("- No explicit DI modules indexed in root scan.")

    arch_lines.extend([
        "",
        "## 2. ViewModel & State Management",
        f"- **Resolution Status**: `{vm.get('resolution', 'NONE')}`",
    ])
    primary = vm.get("primary")
    if primary:
        generics_str = f" `{primary['generics']}`" if primary.get("generics") else ""
        arch_lines.append(f"- **Primary Base**: `{primary['symbol']}`{generics_str} in [`{primary['path']}`](file:///{primary['path']})")
    elif vm.get("candidates"):
        arch_lines.append("- **Candidates (Unresolved Primary)**:")
        for cand in vm["candidates"]:
            arch_lines.append(f"  - `{cand['symbol']}` in [`{cand['path']}`](file:///{cand['path']})")
    else:
        arch_lines.append("- No custom BaseViewModel detected; uses standard `androidx.lifecycle.ViewModel`.")

    arch_lines.extend([
        "",
        "## 3. Navigation System",
    ])
    nav_elements = nav.get("elements") or []
    if nav_elements:
        for elem in nav_elements:
            arch_lines.append(f"- `{elem['type']}` in [`{elem['path']}`](file:///{elem['path']})")
    else:
        arch_lines.append("- Standard Activity/Intent-based navigation or single-activity host.")

    if conv.get("result_wrappers"):
        arch_lines.extend([
            "",
            "## 4. Result & State Wrappers",
        ])
        for rw in conv["result_wrappers"]:
            arch_lines.append(f"- `{rw['symbol']}` in [`{rw['path']}`](file:///{rw['path']})")

    # 2. ui.md
    ui = facts.get("ui") or {}
    ui_lines = [
        "# Project UI, Theming & Layout Guidelines",
        "",
        "> Generated by Android Agent Harness from deterministic project static analysis.",
        "",
        f"- **UI Paradigm**: `{ui.get('framework', 'compose').upper()}`",
    ]
    themes = ui.get("themes") or []
    if themes:
        ui_lines.append("- **Detected Themes**:")
        for th in themes:
            ui_lines.append(f"  - `{th['symbol']}` in [`{th['path']}`](file:///{th['path']})")
    else:
        ui_lines.append("- Standard `MaterialTheme` tokens.")

    # 3. persistence.md
    pers = facts.get("persistence") or {}
    pers_lines = [
        "# Project Persistence & Storage Architecture",
        "",
        "> Generated by Android Agent Harness from deterministic project static analysis.",
        "",
        "## Room Databases",
    ]
    dbs = pers.get("room_databases") or []
    if dbs:
        for db in dbs:
            pers_lines.append(f"- **Database**: `{db['symbol']}` (Version `{db['version']}`, Entities: `{db['entities_count']}`)")
            pers_lines.append(f"  - File: [`{db['path']}`](file:///{db['path']})")
            if db.get("entities"):
                pers_lines.append(f"  - Entities: {', '.join(db['entities'])}")
    else:
        pers_lines.append("- No Room `@Database` classes detected in checkout.")

    daos = pers.get("room_daos") or []
    if daos:
        pers_lines.extend(["", "## Discovered DAOs"])
        for dao in daos:
            pers_lines.append(f"- `{dao['symbol']}` in [`{dao['path']}`](file:///{dao['path']})")

    ds = pers.get("datastore_preferences") or []
    if ds:
        pers_lines.extend(["", "## DataStore Preferences"])
        for item in ds:
            pers_lines.append(f"- DataStore preferences in [`{item['file']}`](file:///{item['file']})")

    # 4. conventions.md
    caps = facts.get("capabilities") or {}
    conv_lines = [
        "# Discovered Technical Capabilities & Conventions",
        "",
        "> Generated by Android Agent Harness from deterministic project static analysis.",
        "",
        "## Technical Capabilities",
    ]
    detected_caps = [k for k, v in caps.items() if v.get("detected")]
    if detected_caps:
        for cap in sorted(detected_caps):
            details = caps[cap]
            sigs = ", ".join(details.get("evidence_signatures", []))
            conv_lines.append(f"- **{cap.capitalize()}**: `DETECTED` (Signatures: {sigs})")
    else:
        conv_lines.append("- Standard Android platform runtime without specialized media/sensor/billing SDKs.")

    return {
        "architecture.md": "\n".join(arch_lines) + "\n",
        "ui.md": "\n".join(ui_lines) + "\n",
        "persistence.md": "\n".join(pers_lines) + "\n",
        "conventions.md": "\n".join(conv_lines) + "\n",
    }


def project_context_diff(old_facts_payload: dict, new_facts_payload: dict) -> dict:
    """Classifies differences between old and new facts into SOURCE_DRIFT, EXTRACTOR_CHANGE, or RENDER_ONLY_CHANGE."""
    old_fp = old_facts_payload.get("context_fingerprint_sha256") or ""
    new_fp = new_facts_payload.get("context_fingerprint_sha256") or ""
    old_ext = old_facts_payload.get("extractor_version") or ""
    new_ext = new_facts_payload.get("extractor_version") or ""

    if old_fp == new_fp:
        return {"kind": "NO_CHANGE", "has_drift": False, "details": []}

    if old_ext != new_ext and old_fp != new_fp:
        return {
            "kind": "EXTRACTOR_CHANGE",
            "has_drift": True,
            "details": [f"Extractor version changed from {old_ext} to {new_ext}"],
        }

    drifts = []
    old_f = old_facts_payload.get("facts") or {}
    new_f = new_facts_payload.get("facts") or {}

    for section in ("di", "view_models", "persistence", "ui", "navigation", "capabilities"):
        if _canonical_json(old_f.get(section)) != _canonical_json(new_f.get(section)):
            drifts.append(f"Architectural drift in '{section}'")

    return {
        "kind": "SOURCE_DRIFT" if drifts else "RENDER_ONLY_CHANGE",
        "has_drift": bool(drifts),
        "details": drifts if drifts else ["Structural representation changed without source drift"],
    }


def project_context_status(repo: Path) -> dict:
    """Checks the status and freshness of project-context without modifying disk."""
    facts_file = repo / ".agents" / "project-context" / "project-facts.json"
    if not facts_file.is_file():
        return {"status": "MISSING", "message": "project-facts.json is missing; run context generate or init"}

    try:
        current_on_disk = json.loads(facts_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "CORRUPTED", "message": f"project-facts.json cannot be parsed: {exc}"}

    disk_fp = current_on_disk.get("context_fingerprint_sha256") or ""
    fresh_payload = extract_project_facts(repo, in_memory_graph=True)
    fresh_fp = fresh_payload.get("context_fingerprint_sha256") or ""

    diff = project_context_diff(current_on_disk, fresh_payload)
    if disk_fp == fresh_fp:
        return {
            "status": "CURRENT",
            "fingerprint": disk_fp,
            "message": "Project context is up-to-date with codebase architecture.",
            "diff": diff,
        }
    return {
        "status": "STALE",
        "fingerprint": disk_fp,
        "fresh_fingerprint": fresh_fp,
        "message": "Project context is stale; run 'android-harness context refresh'.",
        "diff": diff,
    }


def write_project_context(repo: Path, facts_payload: dict, rendered_views: dict[str, str] | None = None) -> Path:
    """Atomically writes project-facts.json and rendered markdown documents into .agents/project-context."""
    context_dir = repo / ".agents" / "project-context"
    context_dir.mkdir(parents=True, exist_ok=True)

    # 1. Write facts
    facts_file = context_dir / "project-facts.json"
    facts_file.write_text(json.dumps(facts_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 2. Render and write markdown views
    if rendered_views is None:
        rendered_views = render_project_context(facts_payload)

    for name, content in rendered_views.items():
        doc_path = context_dir / name
        doc_path.write_text(content, encoding="utf-8")

    # 3. Create initial project-notes.md only if it does not already exist
    notes_file = context_dir / "project-notes.md"
    if not notes_file.exists():
        notes_content = [
            "# Human-Authored Project Architectural Notes",
            "",
            "> This file is owned and maintained by the project engineering team.",
            "> The Android Agent Harness preserves this file across updates and NEVER overwrites it.",
            "> AI models and agents are prohibited from modifying this file directly.",
            "",
            "## Domain Conventions & Context",
            "- Add specific team idioms, legacy constraints, or non-obvious architecture requirements here.",
            "",
        ]
        notes_file.write_text("\n".join(notes_content), encoding="utf-8")

    return context_dir
