"""Generate project configuration and invoke bounded adapter installers."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def generate_product_py(repo: Path, answers: dict) -> Path:
    from _enforcement import detect
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
                candidate = launcher_candidate.split("/", 1)[0].strip()
                if "." in candidate:
                    app_ids = [candidate]
        clean_name = re.sub(r"[^a-zA-Z0-9]", "", product_name).lower() or "app"
        application_id = app_ids[0] if app_ids else f"com.{clean_name}.app"

    project_kind = answers.get("project_kind") or "application"
    launcher = answers.get("launcher") or (f"{application_id}/.MainActivity" if project_kind == "application" else "")
    assemble_task = answers.get("assemble") or ":app:assembleDebug"
    unit_test_task = answers.get("unit_test_task") or assemble_task.replace("assemble", "test") + "UnitTest"
    if "assemble" not in assemble_task:
        unit_test_task = ":app:testDebugUnitTest"
    tracker_language = answers.get("zoho_language") or answers.get("tracker_language") or "en_titles_ar_comments"
    tools = answers.get("tools") or ["gemini"]
    enforcement = detect(repo, tools if isinstance(tools, list) else str(tools).split(","))
    configured_src = answers.get("android_src")
    if not isinstance(configured_src, (list, tuple)) or not configured_src:
        module = str(answers.get("module") or assemble_task.split(":assemble", 1)[0] or ":app")
        module_parts = [part for part in module.split(":") if part]
        source_set = "androidMain" if (repo.joinpath(*module_parts) / "src" / "androidMain").is_dir() else "main"
        configured_src = [*module_parts, "src", source_set]
    values = {
        "PRODUCT_NAME": product_name,
        "PROJECT_KIND": project_kind,
        "APPLICATION_ID": application_id,
        "LAUNCHER": launcher,
        "PACKAGE_PREFIX": ".".join(application_id.split(".")[:2]),
        "ASSEMBLE_TASK": assemble_task,
        "UNIT_TEST_TASK": unit_test_task,
        "APK_RELATIVE": answers.get("apk_path") or "app/build/outputs/apk/debug/app-debug.apk",
        "ANDROID_SRC": tuple(str(item) for item in configured_src),
        "ACTIVE_FLAVOR": "" if answers.get("flavor_mode") == "custom_variant" else answers.get("flavor") or "",
        "ACTIVE_VARIANT": answers.get("build_variant") or "Debug",
        "ASSEMBLE_TASKS": answers.get("assemble_tasks") or {},
        "APK_RELATIVES": answers.get("apk_relatives") or {},
        "CHAT_LANGUAGE": answers.get("chat_language") or "mirror",
        "TRACKER_LANGUAGE": tracker_language,
        "ZOHO_LANGUAGE": tracker_language,
        "ALLOW_EMULATOR": answers.get("device_policy") != "physical-only",
        "DEVICE_TARGET_POLICY": answers.get("device_policy") or "allow",
        "GIT_POLICY": answers.get("git_policy") or "never",
        "INSTALL_CONFIRM": answers.get("install_confirm") or "confirm",
        "PM_PROVIDER": answers.get("pm_provider") or "zoho_sprints",
        "DI_FRAMEWORK": answers.get("di_framework") or "hilt",
        "UI_FRAMEWORK": answers.get("ui_framework") or "compose",
        "SUPPORTED_LOCALES": answers.get("supported_locales") or ["en", "ar"],
        "PROJECT_STRUCTURE": answers.get("project_structure") or "single_module",
        "DEVICE_VERIFICATION_MODE": answers.get("device_verification") or "manual_only",
        "ENFORCEMENT_TIER": enforcement["overall"],
        "ENFORCEMENT_BY_HOST": enforcement["by_host"],
        "MODEL_CALL_BUDGET": int(answers.get("model_call_budget") or 8),
        "ALLOW_MODEL_ESCALATION": bool(answers.get("allow_model_escalation", False)),
    }
    lines = ['"""Generated project identity and vNext policy configuration."""', "from __future__ import annotations", ""]
    lines.extend(f"{key} = {value!r}" for key, value in values.items())
    target = repo / ".agents" / "scripts" / "_product.py"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def configure_adapters_and_mcp(repo: Path, answers: dict) -> None:
    scripts_dir = repo / ".agents" / "scripts"
    tools = answers.get("tools") or ["gemini"]
    tools_arg = ",".join(tools) if isinstance(tools, list) else str(tools)
    adapter_script = scripts_dir / "install_tool_adapters.py"
    if adapter_script.is_file():
        command = [
            sys.executable,
            str(adapter_script),
            "--repo", str(repo),
            "--product", str(answers.get("product") or repo.name),
            "--py", str(answers.get("py") or sys.executable),
            "--assemble", str(answers.get("assemble") or ":app:assembleDebug"),
            "--device-policy", str(answers.get("device_policy") or "allow"),
            "--git-policy", str(answers.get("git_policy") or "never"),
            "--pm-provider", str(answers.get("pm_provider") or "zoho_sprints"),
            "--tracker-language", str(answers.get("zoho_language") or "en_titles_ar_comments"),
            "--tools", tools_arg,
        ]
        if "claude" in tools_arg.split(","):
            command.append("--cc-hooks")
        if "copilot" in tools_arg.split(","):
            command.append("--copilot-hooks")
        proc = subprocess.run(command, cwd=str(repo), capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "adapter generation failed").strip())

    zoho_script = scripts_dir / "install_zoho_mcp.py"
    if zoho_script.is_file():
        mode = "--enable" if answers.get("pm_provider") == "zoho_sprints" and answers.get("zoho_mcp") == "enable" else "--disable"
        command = [
            sys.executable,
            str(zoho_script),
            "--repo", str(repo),
            "--py", str(answers.get("py") or sys.executable),
            "--tools", tools_arg,
            mode,
        ]
        proc = subprocess.run(command, cwd=str(repo), capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "Zoho adapter generation failed").strip())
    # Adapter generation determines which hosts really have executable hooks.
    # Re-emit product configuration from detected capabilities, never answers.
    generate_product_py(repo, answers)
