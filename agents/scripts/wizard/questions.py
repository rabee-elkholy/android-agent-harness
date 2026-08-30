"""Question models, prompts, answer normalization, and answer persistence."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .discovery import (
    _flavor_pascal,
    answers_path,
    auto_blurb,
    auto_from_facts,
    discover,
    markdown_path,
    read_text,
    setup_dir,
)
from .i18n import (
    DEFAULT_PM_PROVIDER,
    PM_PROVIDER_IDS,
    SCHEMA,
    TOOL_IDS,
    TOOL_LABELS,
    t,
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
    qs.append(
        {
            "id": "i22",
            "required": True,
            "allow_multiple": False,
            "prompt": t(lang, "i22"),
            "options": [
                {"id": "autonomous_e2e", "label": t(lang, "i22_e2e")},
                {"id": "manual_only", "label": t(lang, "i22_manual")},
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
    chat_lang = raw.get("i17") or auto.get("chat_language") or "mirror"
    if chat_lang not in {"en", "mirror", "ar"}:
        chat_lang = "mirror"
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
        "di_framework": auto.get("di_framework", "hilt"),
        "ui_framework": auto.get("ui_framework", "compose"),
        "project_structure": auto.get("project_structure", "single_module"),
        "supported_locales": auto.get("supported_locales", ["en", "ar"]),
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
        "device_verification": raw.get("i22") or auto.get("device_verification", "autonomous_e2e"),
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
        f"- I.18 Tracker Language: {answers.get('zoho_language', 'en_titles_ar_comments')}",
        f"- I.19 Daily flavor: {answers.get('flavor') or '(default variant)'}",
        f"- I.20 Project tracker: {answers.get('pm_provider') or DEFAULT_PM_PROVIDER}",
        f"- I.21 Pre-commit git gate: {answers.get('git_gate', 'yes')}",
        f"- I.22 Device verification: {answers.get('device_verification', 'autonomous_e2e')}",
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
    extra = [
        ".harness-setup/",
        ".harness-backup/",
        ".harness-backups/",
        ".agents/state/",
        ".agents/cache/",
        ".agents/__pycache__/",
        "*.diff",
        "*.patch",
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
    ]
    if answers.get("agents_git") != "commit":
        extra.append(".agents/")
    lines = read_text(gi).splitlines()
    for line in extra:
        if line not in lines:
            lines.append(line)
    text = "\n".join(lines)
    if text:
        text += "\n"
    gi.write_text(text, encoding="utf-8")

    agents_gi = repo / ".agents" / ".gitignore"
    if (repo / ".agents").is_dir():
        ag_extra = [
            "state/",
            "cache/",
            "__pycache__/",
            "scripts/__pycache__/",
            "mcp/*/__pycache__/",
            "mcp/zoho_sprints/__pycache__/",
            "mcp/zoho_sprints/zoho_config.json",
            "*zoho*token*",
            "*.secret",
        ]
        ag_lines = read_text(agents_gi).splitlines() if agents_gi.is_file() else []
        for line in ag_extra:
            if line not in ag_lines:
                ag_lines.append(line)
        ag_text = "\n".join(ag_lines)
        if ag_text:
            ag_text += "\n"
        agents_gi.write_text(ag_text, encoding="utf-8")

    exclude_path = repo / ".git" / "info" / "exclude"
    if (repo / ".git").is_dir() or exclude_path.is_file():
        try:
            exclude_path.parent.mkdir(parents=True, exist_ok=True)
            ex_text = exclude_path.read_text(encoding="utf-8") if exclude_path.is_file() else ""
            ex_lines = [ln.strip() for ln in ex_text.splitlines()]
            local_ex = [
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
                "*.secret",
            ]
            added_ex = []
            for pat in local_ex:
                if pat not in ex_lines and pat.rstrip("/") not in ex_lines:
                    added_ex.append(pat)
            if added_ex:
                with exclude_path.open("a", encoding="utf-8", newline="\n") as f:
                    if ex_text and not ex_text.endswith("\n"):
                        f.write("\n")
                    f.write("# Android Harness Kit — Local AI Manifests & Transient State\n")
                    for pat in added_ex:
                        f.write(f"{pat}\n")
        except Exception:
            pass

    for tracked_cand in [".githooks/pre-commit", "AGENTS.md", "GEMINI.md", "CLAUDE.md"]:
        subprocess.run(
            ["git", "update-index", "--assume-unchanged", tracked_cand],
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
        ("i18", "zoho_language"),
        ("i19", "flavor"),
        ("i20", "pm_provider"),
        ("i21", "git_gate"),
        ("i22", "device_verification"),
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
