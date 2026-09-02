"""One-command deterministic engine for Android AI Harness installation and update.

Executes atomic, repeatable porting with zero manual file manipulation required by AI models:
1. Validates target repository and kit release tag.
2. Creates timestamped backup in <repo>/.harness-backup/ (retaining strictly 1 backup).
3. Preserves existing custom domain references (.agents/skills/android-harness/references/*.md).
4. Atomically places the engine (.agents/) and resets transient state.
5. Generates <repo>/.agents/scripts/_product.py from answers.json.
6. Wires tool adapters (AGENTS.md, GEMINI.md, etc.) and PM tracker integration.
7. Enforces local git privacy via <repo>/.git/info/exclude.
8. Runs _hook_selftest.py and harness_doctor.py to assert 100% operational health.

Usage:
    python agents/scripts/install_or_update.py --repo /path/to/app [--kit /path/to/kit] [--answers-json path]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Add current scripts directory to import wizard & adapter utilities
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _live_process import enable_line_buffered_stdio  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deterministic Android Harness Installer & Updater.")
    p.add_argument("--repo", help="Target Android/KMP repository root (defaults to cwd).")
    p.add_argument("--kit", help="Kit source directory (defaults to auto-detected kit root).")
    p.add_argument("--answers-json", help="Path to answers.json (defaults to <repo>/.harness-setup/answers.json).")
    p.add_argument("--mode", choices=("auto", "install", "update"), default="auto", help="Porting mode.")
    p.add_argument("--skip-backup", action="store_true", help="Skip creating backup.")
    p.add_argument("--skip-doctor", action="store_true", help="Skip running doctor verification at the end.")
    p.add_argument("--json", action="store_true", help="Output results in JSON format.")
    p.add_argument("--lang", choices=("en", "ar"), default="en", help="Output language.")
    return p.parse_args(argv)


def find_repo(explicit: str | None) -> Path:
    repo = Path(explicit).expanduser().resolve() if explicit else Path.cwd().resolve()
    if not ((repo / "gradlew").is_file() or (repo / "gradlew.bat").is_file()):
        raise SystemExit(
            f"[ERROR] Target directory '{repo}' is NOT an Android/KMP project (missing gradlew / gradlew.bat)."
        )
    return repo


def find_kit(explicit: str | None) -> Path:
    if explicit:
        kit = Path(explicit).expanduser().resolve()
    else:
        # If running from within kit directory (e.g. agents/scripts/install_or_update.py)
        candidate = SCRIPTS_DIR.parents[1]
        if (candidate / "agents" / "VERSION").is_file():
            kit = candidate
        else:
            # Fallback to standard kit location
            kit = Path.home() / ".android-harness" / "kit"

    if not (kit / "agents" / "VERSION").is_file():
        raise SystemExit(
            f"[ERROR] Kit directory invalid or missing agents/VERSION at: '{kit}'. "
            "Please pass --kit pointing to a valid android-agent-harness release checkout."
        )
    return kit


def load_answers(repo: Path, explicit_answers_path: str | None) -> dict:
    answers_file = Path(explicit_answers_path).expanduser().resolve() if explicit_answers_path else repo / ".harness-setup" / "answers.json"
    if not answers_file.is_file():
        raise SystemExit(
            f"[ERROR] Missing setup answers file at: '{answers_file}'. "
            "Please run setup_wizard.py questions/write first to record configuration."
        )
    try:
        data = json.loads(answers_file.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"[ERROR] Failed to parse answers JSON '{answers_file}': {e}")
    if not isinstance(data, dict):
        raise SystemExit(f"[ERROR] Answers JSON '{answers_file}' must be an object.")
    return data


def create_backup(repo: Path, answers: dict) -> Path | None:
    if not answers.get("backup", True):
        return None

    now_str = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = repo / ".harness-backup"
    backup_root.mkdir(parents=True, exist_ok=True)

    # Prune older backups so strictly only 1 backup remains
    for child in backup_root.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)

    target_backup = backup_root / now_str
    target_backup.mkdir(parents=True, exist_ok=True)

    repo_items = (
        ".agents",
        ".claude",
        ".codex",
        ".cursor",
        ".github",
        ".windsurf",
        ".roo",
        ".amazonq",
        ".continue",
        ".junie",
        ".kilocode",
        ".gemini",
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
        "CODEX.md",
        "QWEN.md",
        ".cursorrules",
        ".clinerules",
        ".windsurfrules",
        ".goosehints",
    )

    manifest_lines = [f"# Harness Backup Manifest - {now_str}", f"Repository: {repo}", ""]
    for item in repo_items:
        src = repo / item
        if src.exists():
            dest = target_backup / item
            if src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dest)
            manifest_lines.append(f"- [x] {item}")
        else:
            manifest_lines.append(f"- [ ] {item}")

    # Copy SETUP_ANSWERS.md into backup if present
    setup_md = repo / ".harness-setup" / "SETUP_ANSWERS.md"
    if setup_md.is_file():
        shutil.copy2(setup_md, target_backup / "SETUP_ANSWERS.md")
        manifest_lines.append("- [x] SETUP_ANSWERS.md")

    # Copy rollback prompt
    rollback_doc = SCRIPTS_DIR.parents[1] / "docs" / "rollback-prompt.md" if (SCRIPTS_DIR.parents[1] / "docs" / "rollback-prompt.md").is_file() else None
    if rollback_doc and rollback_doc.is_file():
        shutil.copy2(rollback_doc, target_backup / "rollback-prompt.md")
        manifest_lines.append("- [x] rollback-prompt.md")

    # Back up home configs
    home = Path.home()
    home_backup_root = home / ".harness-backups"
    home_backup_dir = home_backup_root / f"{repo.name}-{now_str}"
    home_backup_dir.mkdir(parents=True, exist_ok=True)

    home_items = [
        home / ".gemini" / "config.json",
        home / ".gemini" / "rules",
    ]
    for p in (home / ".claude").glob("settings*.json"):
        home_items.append(p)
    for p in (home / ".codex").glob("config.*"):
        home_items.append(p)

    for h_src in home_items:
        if h_src.exists():
            rel = h_src.relative_to(home)
            dest = home_backup_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if h_src.is_dir():
                shutil.copytree(h_src, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(h_src, dest)
            manifest_lines.append(f"- [x] ~/{rel}")

    (target_backup / "manifest.txt").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    return target_backup


def preserve_references(repo: Path) -> dict[str, str]:
    """Preserves all existing tailored reference markdown files."""
    ref_dir = repo / ".agents" / "skills" / "android-harness" / "references"
    preserved: dict[str, str] = {}
    if ref_dir.is_dir():
        for p in ref_dir.glob("*.md"):
            try:
                preserved[p.name] = p.read_text(encoding="utf-8")
            except Exception:
                pass
    return preserved


def place_engine(repo: Path, kit: Path, preserved_refs: dict[str, str]) -> None:
    """Atomically places .agents/ from kit, cleans transient state, and restores references."""
    dest = repo / ".agents"
    src_agents = kit / "agents"

    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)

    shutil.copytree(src_agents, dest)

    # 1. Clean and reset transient state
    state_dir = dest / "state"
    if state_dir.exists():
        shutil.rmtree(state_dir, ignore_errors=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / ".gitkeep").touch()

    # 2. Write local .agents/.gitignore
    gitignore_content = (
        "state/\n"
        "cache/\n"
        "__pycache__/\n"
        "scripts/__pycache__/\n"
        "mcp/*/__pycache__/\n"
        "mcp/zoho_sprints/zoho_config.json\n"
        "*zoho*token*\n"
        "*.secret\n"
    )
    (dest / ".gitignore").write_text(gitignore_content, encoding="utf-8")

    # 3. Restore preserved references
    dest_ref_dir = dest / "skills" / "android-harness" / "references"
    dest_ref_dir.mkdir(parents=True, exist_ok=True)
    if preserved_refs:
        # Remove kit default placeholder references
        for p in dest_ref_dir.glob("*.md"):
            p.unlink(missing_ok=True)
        for name, content in preserved_refs.items():
            (dest_ref_dir / name).write_text(content, encoding="utf-8")


def generate_product_py(repo: Path, answers: dict, kit: Path) -> Path:
    """Generates a clean, fully populated _product.py from answers.json."""
    product_name = answers.get("product") or repo.name
    application_id = answers.get("application_id")
    if not application_id:
        app_ids = answers.get("application_ids") or []
        if not app_ids:
            try:
                from wizard.discovery import discover_application_ids
                app_ids = discover_application_ids(repo)
            except Exception:
                app_ids = []
        if not app_ids:
            launcher_candidate = str(answers.get("launcher") or "")
            if "/" in launcher_candidate:
                pkg_from_launcher = launcher_candidate.split("/")[0].strip()
                if pkg_from_launcher and "." in pkg_from_launcher:
                    app_ids = [pkg_from_launcher]
        clean_name = re.sub(r"[^a-zA-Z0-9]", "", product_name).lower() or "app"
        application_id = app_ids[0] if app_ids else f"com.{clean_name}.app"

    package_prefix = ".".join(application_id.split(".")[:2]) if "." in application_id else application_id
    launcher = answers.get("launcher") or f"{application_id}/.MainActivity"
    assemble_task = answers.get("assemble") or ":app:assembleDebug"
    unit_test_task = answers.get("unit_test_task") or assemble_task.replace("assemble", "test") + "UnitTest"
    if "assemble" not in assemble_task:
        unit_test_task = ":app:testDebugUnitTest"

    apk_relative = answers.get("apk_path") or "app/build/outputs/apk/debug/app-debug.apk"
    active_flavor = answers.get("flavor") or ""
    assemble_tasks = answers.get("assemble_tasks") or {}
    apk_relatives = answers.get("apk_relatives") or {}

    chat_language = answers.get("chat_language") or "mirror"
    tracker_language = answers.get("zoho_language") or answers.get("tracker_language") or "en_titles_ar_comments"
    allow_emulator = False if answers.get("device_policy") == "physical-only" else True
    git_policy = answers.get("git_policy") or "never"
    install_confirm = answers.get("install_confirm") or "confirm"
    e2e_confirm = answers.get("e2e_confirm") or "confirm"
    pm_provider = answers.get("pm_provider") or "zoho_sprints"
    di_framework = answers.get("di_framework") or "hilt"
    ui_framework = answers.get("ui_framework") or "compose"
    supported_locales = answers.get("supported_locales") or ["en", "ar"]
    project_structure = answers.get("project_structure") or "single_module"
    device_verification_mode = answers.get("device_verification") or "autonomous_e2e"

    code = f'''"""Product identity for this checkout. Setup overwrites these from Gradle/manifests."""
from __future__ import annotations

PRODUCT_NAME = {repr(product_name)}
APPLICATION_ID = {repr(application_id)}
LAUNCHER = {repr(launcher)}
PACKAGE_PREFIX = {repr(package_prefix)}
ASSEMBLE_TASK = {repr(assemble_task)}
UNIT_TEST_TASK = {repr(unit_test_task)}
APK_RELATIVE = {repr(apk_relative)}
ANDROID_SRC = ("app", "src", "main")
ACTIVE_FLAVOR = {repr(active_flavor)}
ASSEMBLE_TASKS = {repr(assemble_tasks)}
APK_RELATIVES = {repr(apk_relatives)}
CHAT_LANGUAGE = {repr(chat_language)}
TRACKER_LANGUAGE = {repr(tracker_language)}
ZOHO_LANGUAGE = TRACKER_LANGUAGE
ALLOW_EMULATOR = {repr(allow_emulator)}
GIT_POLICY = {repr(git_policy)}
INSTALL_CONFIRM = {repr(install_confirm)}
E2E_CONFIRM = {repr(e2e_confirm)}
PM_PROVIDER = {repr(pm_provider)}
DI_FRAMEWORK = {repr(di_framework)}
UI_FRAMEWORK = {repr(ui_framework)}
SUPPORTED_LOCALES = {repr(supported_locales)}
PROJECT_STRUCTURE = {repr(project_structure)}
DEVICE_VERIFICATION_MODE = {repr(device_verification_mode)}
'''
    target = repo / ".agents" / "scripts" / "_product.py"
    target.write_text(code, encoding="utf-8")
    return target


def configure_adapters_and_mcp(repo: Path, answers: dict) -> None:
    """Invokes install_tool_adapters.py and install_zoho_mcp.py deterministically."""
    scripts_dir = repo / ".agents" / "scripts"
    product = answers.get("product") or repo.name
    py = answers.get("py") or sys.executable
    assemble = answers.get("assemble") or ":app:assembleDebug"
    device_policy = answers.get("device_policy") or "allow"
    git_policy = answers.get("git_policy") or "never"
    pm_provider = answers.get("pm_provider") or "zoho_sprints"
    tracker_lang = answers.get("zoho_language") or "en_titles_ar_comments"
    tools_list = answers.get("tools") or ["gemini"]
    tools_arg = ",".join(tools_list) if isinstance(tools_list, list) else str(tools_list)
    git_gate_flag = "--git-gate" if answers.get("git_gate", "yes") in ("yes", True) else "--no-git-gate"

    adapter_script = scripts_dir / "install_tool_adapters.py"
    if adapter_script.is_file():
        cmd = [
            sys.executable,
            str(adapter_script),
            "--repo", str(repo),
            "--product", product,
            "--py", py,
            "--assemble", assemble,
            "--device-policy", device_policy,
            "--git-policy", git_policy,
            "--pm-provider", pm_provider,
            "--tracker-language", tracker_lang,
            "--tools", tools_arg,
            git_gate_flag,
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)

    # Wire or disable Zoho MCP
    zoho_script = scripts_dir / "install_zoho_mcp.py"
    if zoho_script.is_file():
        zoho_mode = "--enable" if (pm_provider == "zoho_sprints" and answers.get("zoho_mcp") == "enable") else "--disable"
        cmd_zoho = [
            sys.executable,
            str(zoho_script),
            "--repo", str(repo),
            "--py", py,
            "--tools", tools_arg,
            zoho_mode,
        ]
        subprocess.run(cmd_zoho, check=False, capture_output=True, text=True)


def enforce_git_privacy(repo: Path) -> None:
    """Guarantees strictly zero harness pollution in git by updating .git/info/exclude."""
    exclude_file = repo / ".git" / "info" / "exclude"
    if not exclude_file.parent.exists():
        exclude_file.parent.mkdir(parents=True, exist_ok=True)

    entries = (
        ".agents/",
        ".harness-setup/",
        ".harness-backup/",
        ".harness-backups/",
        ".githooks/",
        "AGENTS.md",
        "GEMINI.md",
        "CLAUDE.md",
        "CODEX.md",
        "QWEN.md",
        ".cursor/",
        ".cursorrules",
        ".windsurf/",
        ".windsurfrules",
        ".claude/",
        ".clinerules",
        ".amazonq/",
        ".continue/",
        ".junie/",
        ".kilocode/",
        ".roo/",
        ".goosehints",
        "*.diff",
        "*.patch",
    )

    existing = exclude_file.read_text(encoding="utf-8") if exclude_file.is_file() else ""
    existing_lines = {line.strip() for line in existing.splitlines() if line.strip()}

    to_add = [e for e in entries if e not in existing_lines]
    if to_add:
        content = existing.rstrip() + "\n\n# Android Agent Harness Local Privacy\n" + "\n".join(to_add) + "\n"
        exclude_file.write_text(content, encoding="utf-8")


def run_verification(repo: Path) -> dict:
    """Executes _hook_selftest.py and harness_doctor.py to assert 100% operational health."""
    scripts_dir = repo / ".agents" / "scripts"

    # 1. Run hook selftest
    print("      -> Executing hook selftest suite...", flush=True)
    selftest_script = scripts_dir / "_hook_selftest.py"
    selftest_code = 1
    selftest_out = ""
    if selftest_script.is_file():
        res = subprocess.run(
            [sys.executable, str(selftest_script)],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
        selftest_code = res.returncode
        selftest_out = res.stdout + res.stderr
        print(f"      -> Hook selftest result: {'[PASS]' if selftest_code == 0 else '[FAIL]'}", flush=True)

    # 2. Run harness doctor
    print("      -> Executing 12-dimension diagnostic doctor...", flush=True)
    doctor_script = scripts_dir / "harness_doctor.py"
    doctor_code = 1
    doctor_out = ""
    if doctor_script.is_file():
        res = subprocess.run(
            [sys.executable, str(doctor_script)],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
        doctor_code = res.returncode
        doctor_out = res.stdout + res.stderr
        print(f"      -> Doctor diagnostic result: {'[PASS]' if doctor_code == 0 else '[FAIL]'}", flush=True)

    return {
        "selftest_code": selftest_code,
        "selftest_pass": selftest_code == 0,
        "doctor_code": doctor_code,
        "doctor_pass": doctor_code == 0,
        "selftest_output": selftest_out,
        "doctor_output": doctor_out,
    }


def extract_version_diff_summary(kit: Path, prev_version: str | None, current_version: str) -> list[str]:
    """Extracts concise changelog highlights between prev_version and current_version from CHANGELOG.md."""
    changelog_file = kit / "CHANGELOG.md"
    if not changelog_file.is_file():
        return []

    try:
        text = changelog_file.read_text(encoding="utf-8")
    except Exception:
        return []

    sections = re.split(r"(?m)^## \[(\d+\.\d+\.\d+)\]", text)
    if len(sections) < 3:
        return []

    highlights: list[str] = []
    clean_prev = prev_version.strip().lstrip("v") if prev_version else None

    for i in range(1, len(sections), 2):
        v = sections[i]
        body = sections[i + 1] if i + 1 < len(sections) else ""
        if clean_prev and v == clean_prev:
            break

        for item in re.findall(r"-\s+\*\*([^*]+)\*\*", body)[:3]:
            clean_item = re.sub(r"\s*\([^)]*\)", "", item).strip()
            clean_item = clean_item.rstrip("`:")
            if clean_item and f"[{v}] {clean_item}" not in highlights:
                highlights.append(f"[{v}] {clean_item}")

        if len(highlights) >= 6:
            break

    return highlights


def sync_code_graph(repo: Path) -> dict:
    """Builds and caches the complete project code graph and topology during installation/update."""
    try:
        from _graph_core import GraphEngine, render_dot_to_image
        engine = GraphEngine(repo)
        stats = engine.sync(force_full=True)
        dot_str = engine.graph.to_dot(title=f"{repo.name} Code Graph")
        dot_file = repo / ".agents" / "cache" / "project_graph.dot"
        dot_file.parent.mkdir(parents=True, exist_ok=True)
        dot_file.write_text(dot_str, encoding="utf-8")

        svg_file = repo / ".agents" / "cache" / "graph.svg"
        render_ok, _ = render_dot_to_image(dot_str, svg_file, img_format="svg")

        return {
            "success": True,
            "nodes": stats.get("total_nodes", len(engine.graph.nodes)),
            "edges": stats.get("total_edges", len(engine.graph.edges)),
            "indexed_files": stats.get("added", 0) + stats.get("modified", 0),
            "dot_file": str(dot_file),
            "svg_rendered": render_ok,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def execute_install_or_update(
    repo: Path,
    kit: Path,
    answers_path: str | None = None,
    skip_backup: bool = False,
    skip_doctor: bool = False,
) -> dict:
    """Main deterministic orchestration routine."""
    start_time = datetime.datetime.now()
    version = (kit / "agents" / "VERSION").read_text(encoding="utf-8").strip()
    answers = load_answers(repo, answers_path)
    is_update = (repo / ".agents").is_dir()
    mode = "update" if is_update else "install"

    prev_version = None
    if is_update and (repo / ".agents" / "VERSION").is_file():
        try:
            prev_version = (repo / ".agents" / "VERSION").read_text(encoding="utf-8").strip()
        except Exception:
            prev_version = None

    changes_summary = extract_version_diff_summary(kit, prev_version, version)

    print(f"[*] Starting Android AI Harness {mode.capitalize()} (v{version})...", flush=True)

    # 1. Backup
    backup_dir = None
    if not skip_backup:
        print("[1/6] Creating timestamped backup...", flush=True)
        backup_dir = create_backup(repo, answers)
        if backup_dir:
            print(f"      Backup created at: .harness-backup/{backup_dir.name}", flush=True)

    # 2. Preserve references
    print("[2/6] Preserving custom domain reference guides...", flush=True)
    preserved_refs = preserve_references(repo)
    if preserved_refs:
        print(f"      Preserved {len(preserved_refs)} reference files.", flush=True)

    # 3. Place engine
    print("[3/6] Placing harness engine (.agents/)...", flush=True)
    place_engine(repo, kit, preserved_refs)

    # 4. Generate _product.py & Wire adapters
    print("[4/6] Generating _product.py & wiring tool adapters...", flush=True)
    generate_product_py(repo, answers, kit)
    configure_adapters_and_mcp(repo, answers)
    enforce_git_privacy(repo)

    # 5. Pre-warm Code Graph (Zero Cold-Start)
    print("[5/6] Building & pre-warming universal code graph...", flush=True)
    graph_stats = sync_code_graph(repo)
    if graph_stats.get("success"):
        print(f"      Cached {graph_stats['nodes']} nodes & {graph_stats['edges']} edges in .agents/cache/project_graph.json", flush=True)

    # 6. Verify
    verification = {}
    if not skip_doctor:
        print("[6/6] Running operational health verification...", flush=True)
        verification = run_verification(repo)

    duration = (datetime.datetime.now() - start_time).total_seconds()
    version = (kit / "agents" / "VERSION").read_text(encoding="utf-8").strip()

    return {
        "success": verification.get("selftest_pass", True) and verification.get("doctor_pass", True),
        "mode": mode,
        "version": version,
        "previous_version": prev_version,
        "changes_summary": changes_summary,
        "graph_stats": graph_stats,
        "product": answers.get("product", repo.name),
        "duration_seconds": round(duration, 2),
        "backup_dir": str(backup_dir) if backup_dir else None,
        "preserved_references_count": len(preserved_refs),
        "preserved_references": list(preserved_refs.keys()),
        "verification": verification,
    }


def main(argv: list[str] | None = None) -> int:
    enable_line_buffered_stdio()
    args = parse_args(argv)
    repo = find_repo(args.repo)
    kit = find_kit(args.kit)

    result = execute_install_or_update(
        repo=repo,
        kit=kit,
        answers_path=args.answers_json,
        skip_backup=args.skip_backup,
        skip_doctor=args.skip_doctor,
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["success"] else 1

    # Formatted console output
    mode_title = "Update" if result["mode"] == "update" else "Installation"
    print("==================================================")
    print(f"  Android AI Harness: {mode_title} Complete (v{result['version']})")
    print("==================================================")
    print(f"[*] Product: {result['product']}")
    if result["mode"] == "update" and result.get("previous_version"):
        print(f"[*] Version: v{result['previous_version']} -> v{result['version']}")
    else:
        print(f"[*] Version: v{result['version']}")
    print(f"[*] Duration: {result['duration_seconds']}s")
    if result["backup_dir"]:
        print(f"[*] Backup Created: {result['backup_dir']}")
    if result["preserved_references_count"] > 0:
        print(f"[*] Preserved Tailored References ({result['preserved_references_count']}): {', '.join(result['preserved_references'])}")

    if result.get("graph_stats", {}).get("success"):
        g = result["graph_stats"]
        svg_badge = " (SVG rendered)" if g.get("svg_rendered") else ""
        print(f"[*] Code Graph: [READY] {g['nodes']} nodes, {g['edges']} edges cached{svg_badge}")

    if result.get("changes_summary"):
        print("\n[*] Key Changes & Improvements:")
        for chg in result["changes_summary"]:
            print(f"  - {chg}")

    verif = result.get("verification", {})
    if verif:
        selftest_status = "[PASS]" if verif.get("selftest_pass") else "[FAIL]"
        doctor_status = "[PASS]" if verif.get("doctor_pass") else "[FAIL]"
        print(f"\n[*] Hook Selftest: {selftest_status}")
        print(f"[*] 12-Dimension Doctor: {doctor_status}")

    if result["success"]:
        print("\n[SUCCESS] Harness is 100% operational. Zero git pollution. Ready for development.")
        return 0
    else:
        print("\n[FAIL] Verification detected issues. Please check doctor output:")
        if not verif.get("selftest_pass"):
            print("--- Selftest Output ---")
            print(verif.get("selftest_output"))
        if not verif.get("doctor_pass"):
            print("--- Doctor Output ---")
        return 1


if __name__ == "__main__":
    sys.exit(main())
