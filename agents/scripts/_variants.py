"""Build-variant (flavor) resolution shared by runners, wizard, and doctor.

Backward compatible: when _product.py predates variants, every resolver falls
back to its configured assemble task. Explicit ``--flavor`` remains a shortcut
for known flavor-to-task mappings; the default task may be any exact combined
variant selected during setup.
"""
from __future__ import annotations

import re
from pathlib import Path

try:
    from _product import ACTIVE_FLAVOR, ASSEMBLE_TASKS, APK_RELATIVES, ASSEMBLE_TASK  # type: ignore
except ImportError:
    ACTIVE_FLAVOR = ""
    ASSEMBLE_TASKS = {}
    APK_RELATIVES = {}
    ASSEMBLE_TASK = ""

try:
    from _product import ACTIVE_VARIANT  # type: ignore
except ImportError:
    ACTIVE_VARIANT = "Debug"

try:
    from _product import MODULE as _APP_MODULE  # type: ignore
except ImportError:
    _APP_MODULE = ""

try:
    from _product import PROJECT_KIND  # type: ignore
except ImportError:
    PROJECT_KIND = "application"


def _default_module() -> str:
    if _APP_MODULE:
        return str(_APP_MODULE)
    try:
        from _product import ASSEMBLE_TASK  # type: ignore

        task = str(ASSEMBLE_TASK or ":app:assembleDebug")
        module = task.split(":assemble")[0]
        return module if module else ":"
    except ImportError:
        return ":app"


def normalize_flavor(name: str | None) -> str:
    if not name:
        return ""
    return re.sub(r"[^a-z0-9_]", "", str(name).strip().lower())


def known_flavors() -> list[str]:
    flavors = {k for k in ASSEMBLE_TASKS.keys() if str(k).strip()}
    flavors |= {k for k in APK_RELATIVES.keys() if str(k).strip()}
    return sorted(f for f in flavors if f)


def active_flavor() -> str:
    return normalize_flavor(str(ACTIVE_FLAVOR or ""))


def pascal(name: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^a-zA-Z0-9]", name) if part)


def resolve_assemble_task(repo: Path | str | None = None, flavor: str | None = None) -> str:
    """Authoritatively resolve final build task from project kind, module, variant, flavor, and topology."""
    prod_dict = {}
    if repo:
        repo_p = Path(repo).resolve()
        for cand in (repo_p / ".agents" / "scripts" / "_product.py", repo_p / "agents" / "scripts" / "_product.py"):
            if cand.is_file():
                try:
                    import importlib.util
                    spec = importlib.util.spec_from_file_location("_dynamic_product", str(cand))
                    if spec and spec.loader:
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)
                        for attr in dir(mod):
                            if not attr.startswith("_"):
                                prod_dict[attr] = getattr(mod, attr)
                        break
                except Exception:
                    pass

    kind = str(prod_dict.get("PROJECT_KIND") or PROJECT_KIND or "application").lower().strip()
    active_fl = normalize_flavor(flavor if flavor is not None else prod_dict.get("ACTIVE_FLAVOR") or ACTIVE_FLAVOR)
    assemble_tasks_map = prod_dict.get("ASSEMBLE_TASKS") if isinstance(prod_dict.get("ASSEMBLE_TASKS"), dict) else ASSEMBLE_TASKS
    if active_fl and isinstance(assemble_tasks_map, dict) and active_fl in assemble_tasks_map:
        return str(assemble_tasks_map[active_fl]).strip()

    active_var = str(prod_dict.get("ACTIVE_VARIANT") or ACTIVE_VARIANT or "Debug").strip()
    configured_task = str(prod_dict.get("ASSEMBLE_TASK") or ASSEMBLE_TASK or "").strip()
    module = str(prod_dict.get("MODULE") or _APP_MODULE or "").strip()

    if not module:
        if configured_task and ":assemble" in configured_task:
            module = configured_task.split(":assemble")[0]
        elif repo:
            try:
                from wizard.discovery import discover_android_modules
                mods = discover_android_modules(Path(repo))
                for m in (":app", ":mobile", ":composeApp", ":androidApp"):
                    if m in mods or m.lstrip(":") in mods:
                        module = m
                        break
                if not module and mods:
                    first = mods[0]
                    module = first if first.startswith(":") else f":{first}"
            except Exception:
                pass
    if not module:
        module = ":app"
    if not module.startswith(":"):
        module = f":{module}"

    if kind == "library":
        if configured_task:
            return configured_task
        if active_var and active_var != "Debug":
            return f"{module.rstrip(':')}:assemble{active_var}"
        return f"{module.rstrip(':')}:assemble"

    if active_fl:
        fl_pascal = pascal(active_fl)
        var_suffix = active_var if active_var and active_var != "Debug" else "Debug"
        if not var_suffix.lower().startswith(active_fl.lower()):
            var_suffix = f"{fl_pascal}{var_suffix}"
        return f"{module.rstrip(':')}:assemble{var_suffix}"

    if configured_task:
        return configured_task

    return f"{module.rstrip(':')}:assemble{active_var or 'Debug'}"


def assemble_task(flavor: str | None = None) -> str:
    return resolve_assemble_task(flavor=flavor)


def apk_relative(flavor: str | None = None) -> str:
    fl = normalize_flavor(flavor if flavor is not None else ACTIVE_FLAVOR)
    if not fl:
        try:
            from _product import APK_RELATIVE  # type: ignore

            return str(APK_RELATIVE or "app/build/outputs/apk/debug/app-debug.apk")
        except ImportError:
            return "app/build/outputs/apk/debug/app-debug.apk"
    mapped = str(APK_RELATIVES.get(fl) or "").strip()
    if mapped:
        return mapped
    module_dir = _default_module().lstrip(":").replace(":", "/") or "app"
    return f"{module_dir}/build/outputs/apk/{fl}/debug/app-{fl}-debug.apk"


def resolve_or_raise(flavor_arg: str | None) -> tuple[str, str]:
    """Return (normalized_flavor, assemble_task); raise SystemExit on unknown flavor."""
    if flavor_arg is None:
        return active_flavor(), assemble_task(None)
    fl = normalize_flavor(flavor_arg)
    known = known_flavors()
    if fl and known and fl not in known:
        raise SystemExit(
            f"[ERROR] Unknown flavor '{fl}'. Known flavors: {', '.join(known)} "
            "(or omit --flavor for the default variant)."
        )
    return fl, assemble_task(fl)
