"""Shared zero-dependency ADB core for the E2E QA engines.

Single source of truth for everything the device-side test engines need:

- UI Automator hierarchy modeling and matching (substring + exact + ambiguity).
- String resource indexing, in-app locale fingerprinting, and target-text
  resolution (supports `stringKey`).
- Declarative flow parser (YAML line-oriented + JSON) with strict validation so
  unknown/typo actions can never pass silently.
- ``DeviceSession``: polling-based synchronization, single-call hierarchy dumps,
  reliable text input (ASCII `input text` + ADBKeyboard broadcast for Arabic),
  verified taps, pid/process-scoped crash detection with a cleared baseline.
- ``FlowExecutor``: a shared step interpreter used by both the QA engine and the
  smoke fallback, so no step semantics are duplicated.

Stdlib only. Works across API 21..35.
"""
from __future__ import annotations

import base64
import dataclasses
import datetime
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env_codes import device_gone_reason  # noqa: E402
from _product import APPLICATION_ID, LAUNCHER  # noqa: E402

BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

# Step actions the engine understands. Anything outside these is a validation
# error (never silently ignored).
KNOWN_ACTIONS = {
    "launchApp", "tapOn", "click", "tap", "longPressOn",
    "inputText", "type", "eraseText", "clearText",
    "hideKeyboard", "dismissKeyguard",
    "scroll", "scrollDown", "scrollUp", "scrollLeft", "scrollRight",
    "swipe", "swipeLeft", "swipeRight", "scrollUntilVisible",
    "back", "pressBack", "pressKey",
    "assertVisible", "assertNotVisible", "assertText", "assertEnabled", "assertClickable",
    "assertChecked", "assertSelected", "setNetwork", "network",
    "takeScreenshot", "screenshot", "wait", "sleep", "stopApp", "repeat",
}

ACTION_ALIASES = {
    "click": "tapOn",
    "tap": "tapOn",
    "type": "inputText",
    "clearText": "eraseText",
    "dismissKeyguard": "hideKeyboard",
    "scrollDown": "scroll",
    "scrollUp": "scroll",
    "scrollLeft": "swipeRight",
    "scrollRight": "swipeLeft",
    "network": "setNetwork",
    "pressBack": "back",
    "screenshot": "takeScreenshot",
    "sleep": "wait",
}


class FlowValidationError(Exception):
    """Raised when a declarative flow/test-case definition is malformed."""


class DeviceGoneError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# UI hierarchy model
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class UINode:
    tag: str
    text: str
    resource_id: str
    content_desc: str
    class_name: str
    package: str
    checkable: bool
    checked: bool
    clickable: bool
    enabled: bool
    focusable: bool
    focused: bool
    scrollable: bool
    long_clickable: bool
    password: bool
    selected: bool
    bounds: tuple[int, int, int, int]
    center: tuple[int, int]
    children: list[UINode] = dataclasses.field(default_factory=list)

    @property
    def width(self) -> int:
        return max(0, self.bounds[2] - self.bounds[0])

    @property
    def height(self) -> int:
        return max(0, self.bounds[3] - self.bounds[1])

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "resource_id": self.resource_id,
            "content_desc": self.content_desc,
            "class_name": self.class_name,
            "clickable": self.clickable,
            "enabled": self.enabled,
            "scrollable": self.scrollable,
            "bounds": list(self.bounds),
            "center": list(self.center),
            "children": [c.to_dict() for c in self.children],
        }


def parse_bounds(raw: str) -> tuple[tuple[int, int, int, int], tuple[int, int]]:
    match = BOUNDS_RE.search(raw)
    if not match:
        return (0, 0, 0, 0), (0, 0)
    x1, y1, x2, y2 = map(int, match.groups())
    return (x1, y1, x2, y2), ((x1 + x2) // 2, (y1 + y2) // 2)


def _element_to_node(elem: ET.Element) -> UINode:
    attrib = elem.attrib
    bounds, center = parse_bounds(attrib.get("bounds", ""))
    node = UINode(
        tag=elem.tag,
        text=attrib.get("text", "").strip(),
        resource_id=attrib.get("resource-id", "").strip(),
        content_desc=attrib.get("content-desc", "").strip(),
        class_name=attrib.get("class", "").strip(),
        package=attrib.get("package", "").strip(),
        checkable=attrib.get("checkable") == "true",
        checked=attrib.get("checked") == "true",
        clickable=attrib.get("clickable") == "true",
        enabled=attrib.get("enabled") == "true",
        focusable=attrib.get("focusable") == "true",
        focused=attrib.get("focused") == "true",
        scrollable=attrib.get("scrollable") == "true",
        long_clickable=attrib.get("long-clickable") == "true",
        password=attrib.get("password") == "true",
        selected=attrib.get("selected") == "true",
        bounds=bounds,
        center=center,
    )
    for child in elem:
        node.children.append(_element_to_node(child))
    return node


def parse_ui_hierarchy(xml_content: str) -> list[UINode]:
    if not xml_content or not xml_content.strip():
        return []
    try:
        idx = xml_content.find("<hierarchy")
        xml_clean = xml_content[idx:] if idx >= 0 else xml_content
        root = ET.fromstring(xml_clean)
        return [_element_to_node(child) for child in root]
    except ET.ParseError:
        return []


def find_nodes(
    nodes: list[UINode],
    *,
    text: str | None = None,
    resource_id: str | None = None,
    content_desc: str | None = None,
    class_name: str | None = None,
    clickable: bool | None = None,
    enabled: bool | None = None,
    scrollable: bool | None = None,
    checked: bool | None = None,
    selected: bool | None = None,
    exact: bool = False,
) -> list[UINode]:
    """Recursively search for nodes matching the query criteria.

    With ``exact=True`` text/content-desc match the whole (case-insensitive)
    value instead of substring, which avoids false matches like "Save" matching
    "Save & Exit".
    """
    results: list[UINode] = []

    def _matches(node: UINode) -> bool:
        if text is not None:
            t_want = text.strip().lower()
            t_have = node.text.lower()
            if not t_have:
                return False
            if exact and t_have != t_want:
                return False
            if not exact and t_want not in t_have:
                return False
        if resource_id is not None:
            r_want = resource_id.strip().lower()
            r_have = node.resource_id.lower()
            if not r_have or (not r_have.endswith(r_want) and r_want not in r_have):
                return False
        if content_desc is not None:
            c_want = content_desc.strip().lower()
            c_have = node.content_desc.lower()
            if not c_have:
                return False
            if exact and c_have != c_want:
                return False
            if not exact and c_want not in c_have:
                return False
        if class_name is not None:
            if not node.class_name or class_name.lower() not in node.class_name.lower():
                return False
        if clickable is not None and node.clickable != clickable:
            return False
        if enabled is not None and node.enabled != enabled:
            return False
        if scrollable is not None and node.scrollable != scrollable:
            return False
        if checked is not None and node.checked != checked:
            return False
        if selected is not None and node.selected != selected:
            return False
        return True

    def _recurse(node_list: list[UINode]) -> None:
        for n in node_list:
            if _matches(n):
                results.append(n)
            _recurse(n.children)

    _recurse(nodes)
    return results


def find_first(nodes: list[UINode], **kwargs) -> UINode | None:
    found = find_nodes(nodes, **kwargs)
    return found[0] if found else None


# ---------------------------------------------------------------------------
# String resources & locale
# ---------------------------------------------------------------------------
_STRING_TAG_RE = re.compile(r'<string(?:\s+[^>]*?)?\s+name="([^"]+)"[^>]*>(.*?)</string>', re.DOTALL)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_ENTITY_RE = re.compile(r"&(amp|lt|gt|quot|apos);")


def _clean_string_value(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<![CDATA[") and value.endswith("]]>"):
        value = value[9:-3]
    value = _TAG_STRIP_RE.sub("", value)
    value = _ENTITY_RE.sub(lambda m: {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}[m.group(1)], value)
    return value.strip()


def index_string_resources(repo: Path) -> dict[str, dict[str, str]]:
    """Index string resources from res/values*/strings.xml mapped by locale."""
    res_map: dict[str, dict[str, str]] = {"default": {}}
    for res_dir in repo.rglob("res/values*"):
        if not res_dir.is_dir():
            continue
        folder_name = res_dir.name.lower()
        if folder_name == "values":
            loc_key = "default"
        elif folder_name.startswith("values-"):
            loc_key = folder_name.replace("values-", "").split("-")[0]
        else:
            continue
        str_file = res_dir / "strings.xml"
        if not str_file.is_file():
            continue
        try:
            content = str_file.read_text(encoding="utf-8", errors="ignore")
            for key, raw in _STRING_TAG_RE.findall(content):
                value = _clean_string_value(raw)
                if not value:
                    continue
                res_map.setdefault(loc_key, {})[key] = value
        except Exception:
            continue
    return res_map


def detect_app_locale(nodes: list[UINode], string_index: dict[str, dict[str, str]]) -> str:
    if not string_index or len(string_index) <= 1:
        return "default"

    visible_texts: set[str] = set()

    def _collect(n_list: list[UINode]) -> None:
        for n in n_list:
            if n.text:
                visible_texts.add(n.text.strip().lower())
            if n.content_desc:
                visible_texts.add(n.content_desc.strip().lower())
            _collect(n.children)

    _collect(nodes)

    scores: dict[str, int] = {}
    for loc, d in string_index.items():
        if loc == "default":
            continue
        scores[loc] = 0
        for val in d.values():
            if val and len(val) >= 2 and val.lower() in visible_texts:
                scores[loc] += 1

    if not scores:
        return "default"
    best_loc, best_score = max(scores.items(), key=lambda item: item[1])
    return best_loc if best_score > 0 else "default"


def resolve_target_text(
    target: str | dict | None,
    active_locale: str,
    string_index: dict[str, dict[str, str]],
) -> str | None:
    if target is None:
        return None
    if isinstance(target, str):
        return target
    if not isinstance(target, dict):
        return None
    if target.get("text"):
        return str(target["text"])
    key = target.get("stringKey")
    if key:
        key = str(key)
        for loc in (active_locale, "default"):
            if loc in string_index and key in string_index[loc]:
                return string_index[loc][key]
    return None


# ---------------------------------------------------------------------------
# Declarative flow parsing & validation
# ---------------------------------------------------------------------------
def _strip_yaml_comment(line: str) -> str:
    """Strip a trailing ` #` comment while respecting single/double quotes."""
    in_single = in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if i > 0 and line[i - 1].isspace():
                return line[:i].rstrip()
    return line.rstrip()


def _unquote(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    return raw


def _parse_scalar(value: str):
    value = value.strip()
    if value.startswith("{") or value.startswith("["):
        try:
            return json.loads(value)
        except Exception:
            return _unquote(value)
    unquoted = _unquote(value)
    lowered = unquoted.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return unquoted


def _coerce_action(action_name: str, value) -> dict:
    """Normalize a `- action: value` pair into a typed step dict."""
    step: dict = {"action": action_name}

    def set_target(v) -> None:
        if isinstance(v, dict):
            step.update(v)
        else:
            step["target"] = v

    if action_name in ("tapOn", "longPressOn", "assertVisible", "assertNotVisible", "scrollUntilVisible"):
        set_target(value)
    elif action_name in ("assertChecked", "assertSelected"):
        if isinstance(value, dict):
            step.update(value)
        elif isinstance(value, bool):
            step["checked" if action_name == "assertChecked" else "selected"] = value
        elif value is not None:
            step["target"] = value
    elif action_name in ("setNetwork", "network"):
        if isinstance(value, dict):
            step.update(value)
        elif isinstance(value, bool):
            step["online"] = value
        elif isinstance(value, str):
            step["status"] = value.lower()
    elif action_name in ("swipeLeft", "swipeRight", "scrollLeft", "scrollRight"):
        if isinstance(value, dict):
            step.update(value)
        elif value is not None:
            step["target"] = value
    elif action_name in ("assertText",):
        if isinstance(value, dict):
            step.update(value)
        else:
            step["text"] = value
    elif action_name in ("inputText",):
        if isinstance(value, dict):
            step.update(value)
        else:
            step["text"] = value
    elif action_name in ("takeScreenshot",):
        step["name"] = str(value)
    elif action_name in ("wait",):
        try:
            step["duration"] = float(value)
        except (TypeError, ValueError):
            step["duration"] = 1.0
    elif action_name in ("pressKey",):
        step["key"] = str(value)
    elif action_name in ("scroll", "swipe"):
        if isinstance(value, dict):
            step.update(value)
        elif value:
            step["direction"] = value
    elif action_name in ("stopApp", "hideKeyboard", "back", "eraseText", "launchApp"):
        pass
    elif value is not None:
        step["value"] = value
    return step


def parse_flow_definition(content: str) -> dict:
    """Parse a declarative flow definition from YAML or JSON.

    Returns ``{"appId": ..., "steps": [...]}``. No external YAML dependency.
    """
    content = (content or "").strip()
    if not content:
        return {"appId": None, "steps": []}

    if content.startswith("{") or content.startswith("["):
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return {"appId": None, "steps": data}
            if isinstance(data, dict):
                return {"appId": data.get("appId") or data.get("app_id"), "steps": data.get("steps") or data.get("actions") or []}
        except Exception:
            pass

    app_id: str | None = None
    steps: list[dict] = []
    lines = content.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        raw = _strip_yaml_comment(lines[i])
        stripped = raw.strip()
        if not stripped or stripped == "---":
            i += 1
            continue

        indent = len(raw) - len(raw.lstrip())

        if indent == 0 and stripped.startswith(("appId:", "app_id:")):
            app_id = _unquote(stripped.split(":", 1)[1])
            i += 1
            continue

        if stripped.startswith("-"):
            body = stripped[1:].strip()
            step: dict = {}
            if ":" in body:
                name, val = body.split(":", 1)
                name = name.strip()
                val = val.strip()
                step = _coerce_action(name, _parse_scalar(val) if val else None)
                # Inline map value: `- tapOn: {id: "x"}` already handled by _parse_scalar.
            else:
                step = {"action": body}

            # Consume following indented key: value lines as step properties.
            j = i + 1
            while j < n:
                nxt_raw = _strip_yaml_comment(lines[j])
                nxt_stripped = nxt_raw.strip()
                if not nxt_stripped:
                    j += 1
                    continue
                nxt_indent = len(nxt_raw) - len(nxt_raw.lstrip())
                if nxt_stripped.startswith("-") or nxt_indent <= indent:
                    break
                if ":" in nxt_stripped:
                    k, v = nxt_stripped.split(":", 1)
                    step[k.strip()] = _parse_scalar(v.strip())
                j += 1
            steps.append(step)
            i = j
            continue

        i += 1

    return {"appId": app_id, "steps": steps}


def canonicalize_steps(steps: list[dict]) -> list[dict]:
    """Apply action aliases so downstream code sees a single canonical action name."""
    canonical: list[dict] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        action = step.get("action") or step.get("command") or ""
        step = dict(step)
        if action in ACTION_ALIASES:
            step["action"] = ACTION_ALIASES[action]
        canonical.append(step)
    return canonical


def validate_flow(flow: dict) -> list[str]:
    """Return a list of validation errors (empty == valid)."""
    errors: list[str] = []
    steps = flow.get("steps") or []
    if not isinstance(steps, list):
        return ["'steps' must be a list"]
    for idx, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            errors.append(f"step {idx} is not a mapping")
            continue
        action = step.get("action") or step.get("command") or ""
        if not action:
            errors.append(f"step {idx} has no 'action'")
            continue
        if action in ACTION_ALIASES:
            action = ACTION_ALIASES[action]
        if action not in KNOWN_ACTIONS:
            errors.append(f"step {idx} uses unknown action '{action}'")
    return errors


# ---------------------------------------------------------------------------
# Diff-aware target discovery (shared by smoke and case generator)
# ---------------------------------------------------------------------------
def discover_diff_targets(repo: Path) -> dict:
    results: dict = {
        "activities": [],
        "target_activity": None,
        "target_activity_component": None,
        "target_strings": [],
        "modified_screens": [],
        "modified_files": [],
    }
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
        for line in (proc.stdout or "").splitlines():
            parts = line.strip().split(maxsplit=1)
            if len(parts) != 2:
                continue
            file_rel = parts[1].strip().strip('"')
            if not file_rel.endswith((".kt", ".java", ".xml")):
                continue
            results["modified_files"].append(file_rel)

            if file_rel.endswith("Activity.kt") or file_rel.endswith("Activity.java"):
                act_name = Path(file_rel).stem
                results["activities"].append(act_name)
                if not results["target_activity"] and act_name != "MainActivity":
                    results["target_activity"] = act_name

            if file_rel.endswith("Screen.kt") or file_rel.endswith("Fragment.kt"):
                results["modified_screens"].append(Path(file_rel).stem)

            if file_rel.endswith("strings.xml"):
                full_p = repo / file_rel
                if full_p.is_file():
                    try:
                        content = full_p.read_text(encoding="utf-8", errors="ignore")
                        for m in re.findall(r'<string name="[^"]+">([^<]+)</string>', content)[:5]:
                            if len(m.strip()) > 3 and not m.strip().startswith("%"):
                                results["target_strings"].append(m.strip())
                    except Exception:
                        continue
    except Exception:
        pass

    if results["target_activity"]:
        act_simple = results["target_activity"]
        for mf in repo.rglob("AndroidManifest.xml"):
            try:
                txt = mf.read_text(encoding="utf-8", errors="ignore")
                for line in txt.splitlines():
                    if act_simple in line and "android:name=" in line:
                        m = re.search(r'android:name="([^"]+)"', line)
                        if m:
                            results["target_activity_component"] = m.group(1)
                            break
            except Exception:
                continue
            if results["target_activity_component"]:
                break
    return results


# ---------------------------------------------------------------------------
# Device session
# ---------------------------------------------------------------------------
class DeviceSession:
    def __init__(self, serial: str, package: str = APPLICATION_ID, launcher: str = LAUNCHER):
        self.serial = serial
        self.package = package
        self.launcher = launcher
        self._screen_wh: tuple[int, int] | None = None
        self._has_adb_keyboard: bool | None = None

    # -- low-level adb -----------------------------------------------------
    def run_adb(self, args: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
        cmd = ["adb", "-s", self.serial, *args]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise DeviceGoneError(f"adb call timed out after {timeout:.0f}s; device may be unresponsive") from None
        gone = device_gone_reason((proc.stdout or "") + "\n" + (proc.stderr or ""))
        if gone:
            raise DeviceGoneError(f"device unavailable: {gone}")
        return proc

    # -- screen ------------------------------------------------------------
    def screen_size(self) -> tuple[int, int] | None:
        if self._screen_wh is not None:
            return self._screen_wh
        proc = self.run_adb(["shell", "wm", "size"], timeout=10.0)
        match = re.search(r"(\d+)\s*x\s*(\d+)", proc.stdout or "")
        if match:
            w, h = int(match.group(1)), int(match.group(2))
            if w > 0 and h > 0:
                self._screen_wh = (w, h)
        return self._screen_wh

    # -- app state ---------------------------------------------------------
    def foreground_package(self) -> str | None:
        # Tier 1: dumpsys window (mCurrentFocus / mFocusedApp / mFocusedWindow)
        proc = self.run_adb(["shell", "dumpsys", "window"], timeout=10.0)
        out = proc.stdout or ""
        m = re.search(r"mCurrentFocus=.*?Window\{[^}]*?\s(?:u\d+\s+)?([\w.]+)/", out)
        if m:
            return m.group(1)
        m = re.search(r"mFocusedApp=.*?ActivityRecord\{[^}]*?\s(?:u\d+\s+)?([\w.]+)/", out)
        if m:
            return m.group(1)
        m = re.search(r"mFocusedWindow=.*?Window\{[^}]*?\s(?:u\d+\s+)?([\w.]+)/", out)
        if m:
            return m.group(1)

        # Tier 2: dumpsys activity activities (fallback for Android 12-15)
        proc_act = self.run_adb(["shell", "dumpsys", "activity", "activities"], timeout=10.0)
        act_out = proc_act.stdout or ""
        m_act = re.search(r"(?:mResumedActivity|topResumedActivity|mFocusedActivity):.*?ActivityRecord\{[^}]*?\s(?:u\d+\s+)?([\w.]+)/", act_out)
        if m_act:
            return m_act.group(1)

        return None

    def current_activity(self) -> str | None:
        proc = self.run_adb(["shell", "dumpsys", "window"], timeout=10.0)
        out = proc.stdout or ""
        m = re.search(r"mCurrentFocus=.*?Window\{[^}]*?\s(?:u\d+\s+)?([\w.]+/[\w.$.]+)\}", out)
        if m:
            return m.group(1)
        m = re.search(r"mCurrentFocus=.*?([\w.]+/[\w.$.]+)", out)
        if m:
            return m.group(1)

        proc_act = self.run_adb(["shell", "dumpsys", "activity", "activities"], timeout=10.0)
        act_out = proc_act.stdout or ""
        m_act = re.search(r"(?:mResumedActivity|topResumedActivity|mFocusedActivity):.*?ActivityRecord\{[^}]*?\s(?:u\d+\s+)?([\w.]+/[\w.$.]+)", act_out)
        if m_act:
            return m_act.group(1)

        return None

    def is_app_foreground(self) -> bool:
        candidates = {self.package}
        if self.launcher and "/" in self.launcher:
            candidates.add(self.launcher.split("/")[0])
        return self.foreground_package() in candidates

    def wait_for_foreground(self, timeout: float = 8.0, interval: float = 0.5) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_app_foreground():
                return True
            time.sleep(interval)
        return self.is_app_foreground()

    def wake_and_unlock(self) -> None:
        self.run_adb(["shell", "input", "keyevent", "224"])  # KEYCODE_WAKEUP
        self.run_adb(["shell", "wm", "dismiss-keyguard"])
        time.sleep(0.3)

    def stop_app(self) -> None:
        self.run_adb(["shell", "am", "force-stop", self.package])
        time.sleep(0.5)

    def press_back(self) -> None:
        self.run_adb(["shell", "input", "keyevent", "4"])
        time.sleep(0.4)

    def press_key(self, key: str) -> None:
        mapping = {"home": "3", "back": "4", "enter": "66", "delete": "67", "menu": "82"}
        code = mapping.get(str(key).lower(), str(key))
        self.run_adb(["shell", "input", "keyevent", code])
        time.sleep(0.3)

    # -- launch ------------------------------------------------------------
    def build_component(self, comp: str) -> str:
        if "/" in comp:
            return comp
        if comp.startswith("."):
            return f"{self.package}/{comp}"
        if comp.startswith(self.package):
            return f"{self.package}/{comp}"
        return f"{self.package}/.{comp}"

    def launch_app_or_target(
        self,
        target_activity: str | None = None,
        target_deeplink: str | None = None,
        stop_first: bool = False,
    ) -> bool:
        if stop_first:
            self.stop_app()

        if target_deeplink:
            self.run_adb(["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", target_deeplink])
            return self.wait_for_foreground()

        if target_activity:
            self.run_adb(["shell", "am", "start", "-n", self.build_component(target_activity)])
            if self.wait_for_foreground(timeout=5.0):
                return True

        main_comp = self.build_component(self.launcher if self.launcher else ".MainActivity")
        self.run_adb(["shell", "am", "start", "-n", main_comp])
        return self.wait_for_foreground()

    # -- permissions -------------------------------------------------------
    def grant_common_permissions(self) -> None:
        permissions = [
            "android.permission.POST_NOTIFICATIONS",
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.ACCESS_COARSE_LOCATION",
            "android.permission.CAMERA",
            "android.permission.READ_MEDIA_IMAGES",
        ]
        target_pkgs = [self.package] if self.package else []
        if self.launcher and "/" in self.launcher:
            l_pkg = self.launcher.split("/")[0].strip()
            if l_pkg and l_pkg not in target_pkgs:
                target_pkgs.append(l_pkg)
        for pkg in target_pkgs:
            for perm in permissions:
                self.run_adb(["shell", "pm", "grant", pkg, perm])

    # -- hierarchy ---------------------------------------------------------
    def _dump_via_execout(self) -> str:
        proc = self.run_adb(["exec-out", "uiautomator", "dump", "/dev/tty"], timeout=20.0)
        return proc.stdout or ""

    def _dump_via_file(self) -> str:
        candidates = ["/data/local/tmp/harness_uidump.xml", "/sdcard/harness_uidump.xml"]
        for target_path in candidates:
            dump = self.run_adb(["shell", "uiautomator", "dump", target_path], timeout=20.0)
            if dump.returncode == 0 or "dumped to" in (dump.stdout or "").lower():
                cat = self.run_adb(["shell", "cat", target_path], timeout=20.0)
                out = cat.stdout or ""
                self.run_adb(["shell", "rm", "-f", target_path], timeout=5.0)
                if "<hierarchy" in out:
                    return out
        return ""

    def dump_hierarchy(self, retries: int = 3) -> list[UINode]:
        for attempt in range(retries):
            raw = self._dump_via_execout()
            if not raw.strip() or "<hierarchy" not in raw:
                raw = self._dump_via_file()
            nodes = parse_ui_hierarchy(raw)
            if nodes:
                return nodes
            time.sleep(0.4 * (attempt + 1))
        return []

    def wait_for(
        self,
        matcher: Callable[[list[UINode]], UINode | None],
        timeout: float = 8.0,
        interval: float = 0.4,
    ) -> UINode | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = matcher(self.dump_hierarchy())
            if found:
                return found
            time.sleep(interval)
        return matcher(self.dump_hierarchy())

    # -- gestures ----------------------------------------------------------
    def tap(self, node: UINode) -> bool:
        if not self.is_app_foreground():
            return False
        cx, cy = node.center
        if cx <= 0 or cy <= 0:
            return False
        self.run_adb(["shell", "input", "tap", str(cx), str(cy)])
        time.sleep(0.6)
        return True

    def long_press(self, node: UINode, duration_ms: int = 800) -> None:
        cx, cy = node.center
        self.run_adb(["shell", "input", "swipe", str(cx), str(cy), str(cx), str(cy), str(duration_ms)])
        time.sleep(0.5)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 350) -> None:
        self.run_adb(["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)])
        time.sleep(0.5)

    def scroll(self, forward: bool) -> bool:
        size = self.screen_size()
        if not size:
            return False
        w, h = size
        cx = w // 2
        y_high = int(h * 0.58)
        y_low = int(h * 0.22)
        if forward:
            self.swipe(cx, y_high, cx, y_low)
        else:
            self.swipe(cx, y_low, cx, y_high)
        return True

    def scroll_down(self) -> bool:
        return self.scroll(forward=True)

    def scroll_up(self) -> bool:
        return self.scroll(forward=False)

    def swipe_left(self, y_pct: float = 0.5, duration_ms: int = 350) -> bool:
        """Swipe left (drag right-to-left) to reveal elements further right."""
        size = self.screen_size()
        if not size:
            return False
        w, h = size
        x_start = int(w * 0.85)
        x_end = int(w * 0.15)
        y = int(h * y_pct)
        self.swipe(x_start, y, x_end, y, duration_ms)
        return True

    def swipe_right(self, y_pct: float = 0.5, duration_ms: int = 350) -> bool:
        """Swipe right (drag left-to-right) to reveal elements further left."""
        size = self.screen_size()
        if not size:
            return False
        w, h = size
        x_start = int(w * 0.15)
        x_end = int(w * 0.85)
        y = int(h * y_pct)
        self.swipe(x_start, y, x_end, y, duration_ms)
        return True

    def scroll_horizontal(self, forward: bool = True) -> bool:
        return self.swipe_left() if forward else self.swipe_right()

    def set_network(self, online: bool) -> tuple[bool, str]:
        """Toggle device Wi-Fi and mobile data. Returns (ok, reason)."""
        state_cmd = "enable" if online else "disable"
        try:
            self.run_adb(["shell", "svc", "wifi", state_cmd], timeout=10.0)
            self.run_adb(["shell", "svc", "data", state_cmd], timeout=10.0)
            time.sleep(1.0)
            return True, ""
        except Exception as exc:
            return False, f"failed to set network {state_cmd}: {exc}"

    # -- keyboard & text ---------------------------------------------------
    def hide_keyboard(self) -> None:
        self.run_adb(["shell", "input", "keyevent", "111"])  # KEYCODE_ESCAPE
        time.sleep(0.2)

    def erase_text(self) -> None:
        proc = self.run_adb(["shell", "input", "keycombination", "KEYCODE_CTRL_LEFT", "KEYCODE_A"])
        if proc.returncode == 0:
            self.run_adb(["shell", "input", "keyevent", "67"])  # KEYCODE_DEL
        else:
            self.run_adb(["shell", "input", "keyevent", "123"])  # KEYCODE_MOVE_END
            for _ in range(30):
                self.run_adb(["shell", "input", "keyevent", "67"])
        time.sleep(0.2)

    def has_adb_keyboard(self) -> bool:
        if self._has_adb_keyboard is None:
            proc = self.run_adb(["shell", "ime", "list", "-s"], timeout=10.0)
            self._has_adb_keyboard = "adbkeyboard" in (proc.stdout or "").lower()
        return self._has_adb_keyboard

    @staticmethod
    def _is_ascii(text: str) -> bool:
        return all(ord(c) < 128 for c in text)

    def input_text(self, text: str, clear_first: bool = False, hide_after: bool = True) -> tuple[bool, str]:
        """Type text into the focused field. Returns (ok, reason)."""
        if clear_first:
            self.erase_text()
        if not text:
            return True, ""
        if not self.is_app_foreground():
            return False, "target app is not foreground"

        if self._is_ascii(text):
            escaped = text.replace(" ", "%s")
            for ch in ("\\", "&", "|", ";", "(", ")", "<", ">", '"', "'", "`"):
                escaped = escaped.replace(ch, "\\" + ch)
            self.run_adb(["shell", "input", "text", escaped])
            time.sleep(0.3)
        elif self.has_adb_keyboard():
            b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
            self.run_adb(["shell", "am", "broadcast", "-a", "ADB_INPUT_B64", "--es", "msg", b64])
            time.sleep(0.3)
        else:
            return False, "non-ASCII input requires the ADB Keyboard IME (adbkeyboard) to be installed"

        if hide_after:
            self.hide_keyboard()
        return True, ""

    def focused_field_value(self) -> str | None:
        nodes = self.dump_hierarchy(retries=2)
        for n in find_nodes(nodes, class_name="EditText"):
            if n.text:
                return n.text
        return None

    # -- logcat ------------------------------------------------------------
    def start_logcat_session(self) -> None:
        self.run_adb(["logcat", "-c"])

    def check_logcat_crashes(self) -> list[dict]:
        proc = self.run_adb(["logcat", "-d", "-v", "brief"], timeout=20.0)
        lines = (proc.stdout or "").splitlines()
        crashes: list[dict] = []
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if "FATAL EXCEPTION" in line:
                block = lines[i:i + 15]
                process_line = next((b for b in block if "Process:" in b), "")
                if self.package in process_line:
                    exc = next((b.strip() for b in block[1:] if b.strip() and "Process:" not in b and not b.strip().startswith("at ")), "")
                    crashes.append({
                        "pattern": "FATAL EXCEPTION",
                        "summary": f"{line.strip()} {('| ' + exc) if exc else ''}".strip(),
                        "stacktrace": "\n".join(block),
                    })
            elif "ANR in " in line and self.package in line:
                crashes.append({"pattern": "ANR", "summary": line.strip(), "stacktrace": line})
            i += 1
        return crashes[:5]

    # -- screenshots -------------------------------------------------------
    def capture_screenshot(self, name: str, out_dir: Path) -> Path | None:
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out_path = out_dir / f"{name}_{stamp}.png"
        try:
            with open(out_path, "wb") as fp:
                proc = subprocess.run(
                    ["adb", "-s", self.serial, "exec-out", "screencap", "-p"],
                    stdout=fp,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=10.0,
                )
            if proc.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 1000:
                return out_path
            out_path.unlink(missing_ok=True)
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Shared step interpreter
# ---------------------------------------------------------------------------
class FlowExecutor:
    """Executes a list of declarative steps against a ``DeviceSession``."""

    def __init__(self, session: DeviceSession, repo: Path, screenshots_dir: Path):
        self.session = session
        self.repo = repo
        self.screenshots_dir = screenshots_dir
        self.string_index = index_string_resources(repo)
        self.active_locale = "default"
        self.screenshots: list[Path] = []

    # -- selector resolution ----------------------------------------------
    def _resolve_selector(self, step: dict) -> tuple[str | None, str | None, str | None]:
        target = step.get("target")
        resource_id = step.get("id") or step.get("testTag") or step.get("resourceId") or step.get("resource_id")
        content_desc = step.get("contentDesc") or step.get("content_desc")
        text = resolve_target_text(target, self.active_locale, self.string_index)
        if not text:
            text = step.get("text") if isinstance(step.get("text"), str) else None

        if isinstance(target, dict):
            resource_id = resource_id or target.get("id") or target.get("testTag") or target.get("resourceId")
            content_desc = content_desc or target.get("contentDesc") or target.get("content_desc")
            if not text:
                text = target.get("text")
        return resource_id, content_desc, text

    def _find_matches(self, nodes: list[UINode], step: dict) -> list[UINode]:
        resource_id, content_desc, text = self._resolve_selector(step)
        exact = bool(step.get("exact", False))
        if resource_id:
            return find_nodes(nodes, resource_id=resource_id)
        if content_desc:
            return find_nodes(nodes, content_desc=content_desc, exact=exact)
        if text:
            return find_nodes(nodes, text=text, exact=exact)
        return []

    def _pick_node(self, matches: list[UINode], step: dict) -> tuple[UINode | None, str | None]:
        if not matches:
            return None, None
        if len(matches) == 1:
            return matches[0], None
        index = step.get("index")
        if index is not None:
            try:
                idx = int(index)
            except (TypeError, ValueError):
                return None, f"invalid index '{index}'"
            if 0 <= idx < len(matches):
                return matches[idx], None
            return None, f"index {idx} out of range for {len(matches)} matches"
        return None, f"ambiguous selector matched {len(matches)} elements; add 'index' or 'id' to disambiguate"

    def _scroll_until(self, step: dict, max_swipes: int = 5) -> UINode | None:
        direction = str(step.get("direction", "down")).lower()

        def matcher(nl: list[UINode]) -> UINode | None:
            matches = self._find_matches(nl, step)
            return matches[0] if matches else None

        for _ in range(max_swipes):
            found = matcher(self.session.dump_hierarchy())
            if found:
                return found
            if direction in ("left", "scrollleft", "swipeleft"):
                self.session.swipe_left()
            elif direction in ("right", "scrollright", "swiperight"):
                self.session.swipe_right()
            else:
                self.session.scroll(direction != "up")
            time.sleep(0.3)
        return matcher(self.session.dump_hierarchy())

    # -- main entry --------------------------------------------------------
    def prepare(self, target_activity=None, target_deeplink=None, stop_first=False) -> bool:
        self.session.wake_and_unlock()
        self.session.grant_common_permissions()
        if not self.session.launch_app_or_target(target_activity, target_deeplink, stop_first):
            return False
        nodes = self.session.dump_hierarchy()
        self.active_locale = detect_app_locale(nodes, self.string_index)
        return True

    def execute(self, steps: list[dict]) -> dict:
        """Run steps, stopping at the first hard failure. Returns a result dict."""
        steps_out: list[dict] = []
        self.session.start_logcat_session()
        self._network_modified = False

        try:
            for idx, step in enumerate(steps, start=1):
                action = step.get("action", "")
                desc = f"Step {idx}: {action}"

                outcome = self._run_step(idx, desc, step, steps_out)
                if outcome.get("verdict") == "FAIL":
                    return outcome
                # Crash scan after every step (cheap now: baseline was cleared).
                crashes = self.session.check_logcat_crashes()
                if crashes:
                    return self._fail(idx, desc, f"runtime crash: {crashes[0]['summary']}", self.session.dump_hierarchy(), "RUNTIME_CRASH", steps_out)

            final_shot = self.session.capture_screenshot("flow_final", self.screenshots_dir)
            return {
                "verdict": "PASS",
                "locale": self.active_locale,
                "steps": steps_out,
                "crashes": [],
                "final_screenshot": str(final_shot) if final_shot else None,
            }
        finally:
            if getattr(self, "_network_modified", False):
                try:
                    self.session.set_network(online=True)
                except Exception:
                    pass

    # -- step handlers -----------------------------------------------------
    def _run_step(self, idx: int, desc: str, step: dict, steps_out: list[dict]) -> dict:
        action = step.get("action", "")

        if action == "launchApp":
            stop_first = bool(step.get("stopApp", step.get("clearState", False)))
            ok = self.session.launch_app_or_target(stop_first=stop_first)
            self.active_locale = detect_app_locale(self.session.dump_hierarchy(), self.string_index)
            steps_out.append({"step": desc, "status": "PASS" if ok else "FAIL"})
            if not ok:
                return self._fail(idx, desc, "app launch failed", [], "ASSERTION_FAILED", steps_out)

        elif action in ("tapOn", "longPressOn"):
            matches = self._find_matches(self.session.dump_hierarchy(), step)
            node, err = self._pick_node(matches, step)
            if not node and (step.get("scroll") == "true" or step.get("auto_scroll") == "true"):
                node = self._scroll_until(step)
                err = None
            if not node:
                return self._fail(idx, desc, err or "target element not found", self.session.dump_hierarchy(), "ASSERTION_FAILED", steps_out)
            if action == "longPressOn":
                self.session.long_press(node)
            else:
                if not self.session.tap(node):
                    return self._fail(idx, desc, "tap aborted (app not foreground)", self.session.dump_hierarchy(), "ASSERTION_FAILED", steps_out)
            steps_out.append({"step": desc, "status": "PASS"})
            time.sleep(float(step.get("wait", 0.3)))

        elif action == "inputText":
            text = str(step.get("text") or step.get("value") or "")
            ok, reason = self.session.input_text(
                text,
                clear_first=bool(step.get("clear", step.get("erase", False))),
                hide_after=bool(step.get("hideKeyboard", True)),
            )
            if not ok:
                return self._fail(idx, desc, reason or "text input failed", self.session.dump_hierarchy(), "ASSERTION_FAILED", steps_out)
            steps_out.append({"step": desc, "status": "PASS"})

        elif action == "eraseText":
            self.session.erase_text()
            steps_out.append({"step": desc, "status": "PASS"})

        elif action == "hideKeyboard":
            self.session.hide_keyboard()
            steps_out.append({"step": desc, "status": "PASS"})

        elif action == "scroll":
            direction = str(step.get("direction", "down")).lower()
            if direction in ("left", "scrollleft", "swipeleft"):
                ok = self.session.swipe_left()
            elif direction in ("right", "scrollright", "swiperight"):
                ok = self.session.swipe_right()
            else:
                ok = self.session.scroll(direction != "up")
            steps_out.append({"step": desc, "status": "PASS" if ok else "WARN"})

        elif action == "swipe":
            direction = str(step.get("direction", "down")).lower()
            if direction in ("left", "scrollleft", "swipeleft"):
                ok = self.session.swipe_left()
            elif direction in ("right", "scrollright", "swiperight"):
                ok = self.session.swipe_right()
            else:
                ok = self.session.scroll(direction != "up")
            steps_out.append({"step": desc, "status": "PASS" if ok else "WARN"})

        elif action in ("swipeLeft", "scrollRight"):
            ok = self.session.swipe_left()
            steps_out.append({"step": desc, "status": "PASS" if ok else "WARN"})

        elif action in ("swipeRight", "scrollLeft"):
            ok = self.session.swipe_right()
            steps_out.append({"step": desc, "status": "PASS" if ok else "WARN"})

        elif action == "scrollUntilVisible":
            node = self._scroll_until(step, max_swipes=int(step.get("maxSwipes", 5)))
            if not node:
                return self._fail(idx, desc, "element did not appear after scrolling", self.session.dump_hierarchy(), "ASSERTION_FAILED", steps_out)
            steps_out.append({"step": desc, "status": "PASS"})

        elif action == "back":
            self.session.press_back()
            steps_out.append({"step": desc, "status": "PASS"})

        elif action == "pressKey":
            self.session.press_key(str(step.get("key", "back")))
            steps_out.append({"step": desc, "status": "PASS"})

        elif action in ("assertVisible", "assertNotVisible", "assertEnabled", "assertClickable"):
            nodes = self.session.dump_hierarchy()
            matches = self._find_matches(nodes, step)
            if action == "assertVisible":
                if not matches:
                    return self._fail(idx, desc, "expected element not visible", nodes, "ASSERTION_FAILED", steps_out)
            elif action == "assertNotVisible":
                if matches:
                    return self._fail(idx, desc, "element unexpectedly visible", nodes, "ASSERTION_FAILED", steps_out)
            elif action == "assertEnabled":
                if not matches or any(not n.enabled for n in matches):
                    return self._fail(idx, desc, "element not enabled", nodes, "ASSERTION_FAILED", steps_out)
            elif action == "assertClickable":
                if not matches or any(not n.clickable for n in matches):
                    return self._fail(idx, desc, "element not clickable", nodes, "ASSERTION_FAILED", steps_out)
            steps_out.append({"step": desc, "status": "PASS"})

        elif action in ("assertChecked", "assertSelected"):
            expected = step.get("checked" if action == "assertChecked" else "selected")
            if expected is None:
                expected = step.get("value", True)
            if isinstance(expected, str):
                expected = expected.lower() in ("true", "1", "yes")
            expected_bool = bool(expected)

            nodes = self.session.dump_hierarchy()
            matches = self._find_matches(nodes, step)
            if not matches:
                return self._fail(idx, desc, "expected element not found for state assertion", nodes, "ASSERTION_FAILED", steps_out)
            node, err = self._pick_node(matches, step)
            if not node:
                return self._fail(idx, desc, err or "unable to select target element", nodes, "ASSERTION_FAILED", steps_out)

            actual_val = node.checked if action == "assertChecked" else node.selected
            if actual_val != expected_bool:
                attr_name = "checked" if action == "assertChecked" else "selected"
                return self._fail(
                    idx,
                    desc,
                    f"state assertion failed: element {attr_name} is {actual_val}, expected {expected_bool}",
                    nodes,
                    "ASSERTION_FAILED",
                    steps_out,
                )
            steps_out.append({"step": desc, "status": "PASS", "state": f"{action}={actual_val}"})

        elif action in ("setNetwork", "network"):
            raw_status = str(step.get("status") or step.get("value") or "").lower()
            online_val = step.get("online")
            if online_val is None:
                online_val = raw_status not in ("offline", "disabled", "false", "0", "off")
            online_bool = bool(online_val)
            ok, err = self.session.set_network(online_bool)
            if not ok:
                return self._fail(idx, desc, err or "network switch failed", [], "ENV_FAILURE", steps_out)
            self._network_modified = not online_bool
            steps_out.append({"step": f"{desc} ({'online' if online_bool else 'offline'})", "status": "PASS"})

        elif action == "assertText":
            _, _, expected = self._resolve_selector(step)
            expected = expected or str(step.get("text") or "")
            nodes = self.session.dump_hierarchy()
            exact = bool(step.get("exact", False))
            if expected and find_first(nodes, text=expected, exact=exact) is None:
                return self._fail(idx, desc, f"text '{expected}' not present", nodes, "ASSERTION_FAILED", steps_out)
            steps_out.append({"step": desc, "status": "PASS"})

        elif action == "takeScreenshot":
            shot = self.session.capture_screenshot(str(step.get("name") or f"step_{idx}"), self.screenshots_dir)
            if shot:
                self.screenshots.append(shot)
            steps_out.append({"step": desc, "status": "PASS", "screenshot": str(shot) if shot else None})

        elif action == "wait":
            time.sleep(float(step.get("duration", 1.0)))
            steps_out.append({"step": desc, "status": "PASS"})

        elif action == "stopApp":
            self.session.stop_app()
            steps_out.append({"step": desc, "status": "PASS"})

        elif action == "repeat":
            repeat_steps = step.get("steps") or step.get("body") or []
            times = int(step.get("times", 1))
            for _ in range(times):
                for sub in repeat_steps:
                    if not isinstance(sub, dict):
                        continue
                    sub = dict(sub)
                    sub["action"] = sub.get("action") or ""
                    outcome = self._run_step(idx, f"{desc} (repeat)", sub, steps_out)
                    if outcome.get("verdict") == "FAIL":
                        return outcome
                    crashes = self.session.check_logcat_crashes()
                    if crashes:
                        return self._fail(idx, desc, f"runtime crash: {crashes[0]['summary']}", self.session.dump_hierarchy(), "RUNTIME_CRASH", steps_out)
            steps_out.append({"step": desc, "status": "PASS"})

        else:
            return self._fail(idx, desc, f"unsupported action '{action}'", self.session.dump_hierarchy(), "ASSERTION_FAILED", steps_out)

        return {"verdict": "PASS"}

    # -- failure forensics -------------------------------------------------
    def _fail(self, idx: int, desc: str, reason: str, nodes: list[UINode], classification: str, steps_out: list[dict]) -> dict:
        shot = self.session.capture_screenshot(f"failed_step{idx}", self.screenshots_dir)
        if shot:
            self.screenshots.append(shot)
        crashes = self.session.check_logcat_crashes()
        if crashes:
            classification = "RUNTIME_CRASH"
            reason = f"{reason}; crash: {crashes[0]['summary']}"
        steps_out.append({"step": desc, "status": "FAIL", "reason": reason})
        return {
            "verdict": "FAIL",
            "reason": reason,
            "classification": classification,
            "steps": steps_out,
            "crashes": crashes,
            "screenshot": str(shot) if shot else None,
            "hierarchy_nodes": [n.to_dict() for n in nodes][:200],
        }
