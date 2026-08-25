"""Build-variant (flavor) resolution shared by runners, wizard, and doctor.

Backward compatible: when _product.py predates flavors, every resolver falls
back to the classic single-variant behavior (empty flavor = default variant).
Only Debug variants of flavors are supported — daily work is debug per policy.
"""
from __future__ import annotations

import re

try:
    from _product import ACTIVE_FLAVOR, ASSEMBLE_TASKS, APK_RELATIVES  # type: ignore
except ImportError:
    ACTIVE_FLAVOR = ""
    ASSEMBLE_TASKS = {}
    APK_RELATIVES = {}

try:
    from _product import MODULE as _APP_MODULE  # type: ignore
except ImportError:
    _APP_MODULE = ""


def _default_module() -> str:
    if _APP_MODULE:
        return str(_APP_MODULE)
    try:
        from _product import ASSEMBLE_TASK  # type: ignore

        task = str(ASSEMBLE_TASK or ":app:assembleDebug")
        return task.split(":assemble")[0] or ":app"
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


def assemble_task(flavor: str | None = None) -> str:
    fl = normalize_flavor(flavor if flavor is not None else ACTIVE_FLAVOR)
    if not fl:
        try:
            from _product import ASSEMBLE_TASK  # type: ignore

            return str(ASSEMBLE_TASK or ":app:assembleDebug")
        except ImportError:
            return ":app:assembleDebug"
    mapped = str(ASSEMBLE_TASKS.get(fl) or "").strip()
    if mapped:
        return mapped
    return f"{_default_module()}:assemble{pascal(fl)}Debug"


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
    fl = normalize_flavor(flavor_arg) if flavor_arg is not None else active_flavor()
    known = known_flavors()
    if fl and known and fl not in known:
        raise SystemExit(
            f"[ERROR] Unknown flavor '{fl}'. Known flavors: {', '.join(known)} "
            "(or omit --flavor for the default variant)."
        )
    return fl, assemble_task(fl)
