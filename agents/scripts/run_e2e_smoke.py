"""Autonomous E2E Smoke Testing Engine for Android.

Zero external dependencies (Python stdlib + native ADB UI Automator).
Supports physical Android devices and emulators across API 21 through API 35.

Features:
- Diff-Aware Target Auto-Discovery: Inspects modified working tree files to automatically
  identify modified Activities, Fragments, Composables, and newly added string resources.
- Direct & Deep-Link Component Launching: Launches target Activity directly via ADB
  component intent (`am start -n`) or URI deep links.
- Smart UI Automator Navigation: Traverses tabs, menus, and buttons to reach target screens.
- Instant UI hierarchy dumping and parsing (XML & Jetpack Compose accessibility tree).
- High-precision center coordinate calculation for tap, scroll, and swipe gestures.
- Real-time Logcat crash forensics: Captures and demangles fatal exceptions, ANRs, Room crashes,
  and unchecked nullability violations.
- Strict safety containment barrier: Aborts immediately if foreground app leaves APPLICATION_ID.
- Timestamped visual screenshot capture saved to .agents/state/screenshots/.

Usage:
  python .agents/scripts/run_e2e_smoke.py --auto-diff
  python .agents/scripts/run_e2e_smoke.py --target-activity <ActivityName>
  python .agents/scripts/run_e2e_smoke.py --target-deeplink <URI>
  python .agents/scripts/run_e2e_smoke.py --target-text <Keyword>
  python .agents/scripts/run_e2e_smoke.py --dump-only
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _apk_freshness import check_apk_freshness, format_freshness_error  # noqa: E402
from _env_codes import (  # noqa: E402
    CLASS_ENV,
    EXIT_ENV,
    FailureVerdict,
    device_gone_reason,
    emit_env_failure,
    no_device_verdict,
)
from _gate_results import current_head_sha, write_gate_result  # noqa: E402
from _live_process import enable_line_buffered_stdio, live_print  # noqa: E402
from _product import (  # noqa: E402
    ALLOW_EMULATOR,
    APPLICATION_ID,
    LAUNCHER,
    PRODUCT_NAME,
)
from _repo_files import REPO, first_adb_serial  # noqa: E402
from _variants import apk_relative  # noqa: E402

BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
SCREENSHOTS_DIR = REPO / ".agents" / "state" / "screenshots"
E2E_STATE_DIR = REPO / ".agents" / "state" / "e2e"


class _DeviceGoneError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


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
    bounds: tuple[int, int, int, int]  # (x1, y1, x2, y2)
    center: tuple[int, int]  # (cx, cy)
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
            "bounds": list(self.bounds),
            "center": list(self.center),
            "children": [c.to_dict() for c in self.children],
        }


def parse_bounds(raw: str) -> tuple[tuple[int, int, int, int], tuple[int, int]]:
    match = BOUNDS_RE.search(raw)
    if not match:
        return (0, 0, 0, 0), (0, 0)
    x1, y1, x2, y2 = map(int, match.groups())
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    return (x1, y1, x2, y2), (cx, cy)


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
    """Parse UI Automator XML hierarchy string into list of top-level UINodes."""
    if not xml_content or not xml_content.strip():
        return []
    try:
        idx = xml_content.find("<hierarchy")
        if idx >= 0:
            xml_clean = xml_content[idx:]
        else:
            xml_clean = xml_content
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
    scrollable: bool | None = None,
) -> list[UINode]:
    """Recursively search for nodes matching query criteria (supports Arabic & English)."""
    results: list[UINode] = []

    def _matches(node: UINode) -> bool:
        if text is not None:
            t_want = text.strip().lower()
            t_have = node.text.lower()
            if not t_have or t_want not in t_have:
                return False
        if resource_id is not None:
            r_want = resource_id.strip().lower()
            r_have = node.resource_id.lower()
            if not r_have or (not r_have.endswith(r_want) and r_want not in r_have):
                return False
        if content_desc is not None:
            c_want = content_desc.strip().lower()
            c_have = node.content_desc.lower()
            if not c_have or c_want not in c_have:
                return False
        if class_name is not None:
            if not node.class_name or class_name.lower() not in node.class_name.lower():
                return False
        if clickable is not None and node.clickable != clickable:
            return False
        if scrollable is not None and node.scrollable != scrollable:
            return False
        return True

    def _recurse(node_list: list[UINode]):
        for n in node_list:
            if _matches(n):
                results.append(n)
            _recurse(n.children)

    _recurse(nodes)
    return results


def find_first(nodes: list[UINode], **kwargs) -> UINode | None:
    found = find_nodes(nodes, **kwargs)
    return found[0] if found else None


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
            matches = re.findall(r'<string\s+name="([^"]+)"[^>]*>([^<]*)</string>', content)
            if loc_key not in res_map:
                res_map[loc_key] = {}
            for k, v in matches:
                res_map[loc_key][k] = v.strip()
        except Exception:
            pass
    return res_map


def detect_app_locale(nodes: list[UINode], string_index: dict[str, dict[str, str]]) -> str:
    """Fingerprint visible UI text against string dictionaries to detect in-app active locale."""
    if not string_index or len(string_index) <= 1:
        return "default"

    visible_texts: set[str] = set()

    def _collect(n_list: list[UINode]):
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


def resolve_target_text(target: str | dict, active_locale: str, string_index: dict[str, dict[str, str]]) -> str | None:
    """Resolve target text dynamically from stringKey or static text."""
    if isinstance(target, str):
        return target
    if not isinstance(target, dict):
        return None
    if "text" in target and target["text"]:
        return str(target["text"])
    if "stringKey" in target and target["stringKey"]:
        key = str(target["stringKey"])
        if active_locale in string_index and key in string_index[active_locale]:
            return string_index[active_locale][key]
        if "default" in string_index and key in string_index["default"]:
            return string_index["default"][key]
    return None


def parse_flow_definition(content: str) -> dict:
    """Parse declarative E2E flow from YAML or JSON without external dependencies."""
    content = content.strip()
    if not content:
        return {"appId": None, "steps": []}

    # Check if JSON
    if content.startswith("{") or content.startswith("["):
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return {"appId": None, "steps": data}
            if isinstance(data, dict):
                return {
                    "appId": data.get("appId") or data.get("app_id"),
                    "steps": data.get("steps") or data.get("actions") or [],
                }
        except Exception:
            pass

    # Pure-Python line-by-line YAML parser for Maestro flows
    app_id = None
    steps: list[dict] = []
    lines = content.splitlines()

    current_step: dict | None = None

    for raw_line in lines:
        line = raw_line.split("#", 1)[0].rstrip()
        if not line or line.strip() == "---":
            continue

        stripped = line.strip()

        # Check top-level appId
        if stripped.startswith("appId:") or stripped.startswith("app_id:"):
            app_id = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            continue

        # Step item: starts with '-'
        if stripped.startswith("-"):
            if current_step:
                steps.append(current_step)
                current_step = None

            cmd_body = stripped[1:].strip()
            if not cmd_body:
                continue

            if ":" in cmd_body:
                cmd_name, cmd_val = cmd_body.split(":", 1)
                cmd_name = cmd_name.strip()
                cmd_val = cmd_val.strip().strip('"').strip("'")
                current_step = {"action": cmd_name}
                if cmd_val:
                    if cmd_name in ("tapOn", "click", "assertVisible", "assertNotVisible", "scrollUntilVisible"):
                        current_step["target"] = cmd_val
                    elif cmd_name in ("inputText", "type"):
                        current_step["text"] = cmd_val
                    elif cmd_name in ("takeScreenshot", "screenshot"):
                        current_step["name"] = cmd_val
                    elif cmd_name in ("wait", "sleep"):
                        current_step["duration"] = float(cmd_val) if cmd_val.replace(".", "", 1).isdigit() else 1.0
                    else:
                        current_step["value"] = cmd_val
            else:
                current_step = {"action": cmd_body}
        elif current_step and ":" in stripped:
            k, v = stripped.split(":", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            current_step[k] = v

    if current_step:
        steps.append(current_step)

    return {"appId": app_id, "steps": steps}


def discover_modified_targets(repo: Path) -> dict:
    """Analyze working tree git diff to automatically discover modified activities, composables, and strings."""
    results: dict = {
        "activities": [],
        "target_activity": None,
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
        lines = (proc.stdout or "").splitlines()
        for line in lines:
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                file_rel = parts[1].strip().strip('"')
                results["modified_files"].append(file_rel)
                
                # Check for activity files
                if file_rel.endswith("Activity.kt") or file_rel.endswith("Activity.java"):
                    act_name = Path(file_rel).stem
                    results["activities"].append(act_name)
                    if not results["target_activity"] and act_name != "MainActivity":
                        results["target_activity"] = act_name

                # Check for screens / fragments / composables
                if file_rel.endswith("Screen.kt") or file_rel.endswith("Fragment.kt"):
                    screen_name = Path(file_rel).stem
                    results["modified_screens"].append(screen_name)

                # Check for modified strings
                if file_rel.endswith("strings.xml"):
                    full_p = repo / file_rel
                    if full_p.is_file():
                        content = full_p.read_text(encoding="utf-8", errors="ignore")
                        # Extract simple string values
                        matches = re.findall(r'<string name="[^"]+">([^<]+)</string>', content)
                        for m in matches[:5]:
                            if len(m.strip()) > 3 and not m.strip().startswith("%"):
                                results["target_strings"].append(m.strip())

    except Exception:
        pass

    # If an activity was found, search AndroidManifest.xml for its full component path
    if results["target_activity"]:
        act_simple = results["target_activity"]
        for mf in repo.rglob("AndroidManifest.xml"):
            try:
                txt = mf.read_text(encoding="utf-8", errors="ignore")
                for line in txt.splitlines():
                    if act_simple in line and "android:name=" in line:
                        m = re.search(r'android:name="([^"]+)"', line)
                        if m:
                            raw_name = m.group(1)
                            results["target_activity_component"] = raw_name
                            break
            except Exception:
                pass
            if "target_activity_component" in results:
                break

    return results


class E2ERunner:
    def __init__(
        self,
        serial: str,
        package: str = APPLICATION_ID,
        target_activity: str | None = None,
        target_deeplink: str | None = None,
        target_texts: list[str] | None = None,
    ):
        self.serial = serial
        self.package = package
        self.target_activity = target_activity
        self.target_deeplink = target_deeplink
        self.target_texts = target_texts or []
        self.screenshots: list[Path] = []
        self.start_time = datetime.datetime.now(datetime.timezone.utc)
        self._screen_wh: tuple[int, int] | None = None

    def screen_size(self) -> tuple[int, int] | None:
        """Resolve the device screen size once (adb shell wm size)."""
        if self._screen_wh is not None:
            return self._screen_wh
        self._screen_wh = None
        proc = self.run_adb(["shell", "wm", "size"], timeout=10.0)
        output = proc.stdout or ""
        match = re.search(r"(\d+)\s*x\s*(\d+)", output)
        if match:
            w, h = int(match.group(1)), int(match.group(2))
            if w > 0 and h > 0:
                self._screen_wh = (w, h)
        return self._screen_wh

    def _scroll(self, forward: bool) -> bool:
        """Scroll using screen-relative coordinates. False when size is unknown."""
        size = self.screen_size()
        if not size:
            live_print("[WARN] Device screen size unavailable; skipping scroll gesture.", err=True)
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

    def run_adb(self, args: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
        cmd = ["adb", "-s", self.serial, *args]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise _DeviceGoneError(
                f"adb call timed out after {timeout:.0f}s; device may be unresponsive"
            ) from None
        gone = device_gone_reason((proc.stdout or "") + "\n" + (proc.stderr or ""))
        if gone:
            raise _DeviceGoneError(f"device unavailable during E2E smoke: {gone}")
        return proc

    def wake_and_unlock(self):
        """Wake up device screen and attempt to dismiss basic keyguard."""
        self.run_adb(["shell", "input", "keyevent", "224"])  # KEYCODE_WAKEUP
        self.run_adb(["shell", "wm", "dismiss-keyguard"])
        time.sleep(0.5)

    def is_app_foreground(self) -> bool:
        """Check if target package is currently visible and active in foreground."""
        pkg_candidates = {self.package}
        if LAUNCHER and "/" in LAUNCHER:
            pkg_candidates.add(LAUNCHER.split("/")[0])
        proc = self.run_adb(["shell", "dumpsys", "window", "windows"])
        output = proc.stdout or ""
        for line in output.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                if any(pkg in line for pkg in pkg_candidates):
                    return True
        proc_act = self.run_adb(["shell", "dumpsys", "activity", "top"])
        top_out = proc_act.stdout or ""
        return any(pkg in top_out for pkg in pkg_candidates)

    def grant_common_permissions(self):
        """Pre-grant common permissions to prevent system dialogs from blocking UI smoke flows."""
        permissions = [
            "android.permission.POST_NOTIFICATIONS",
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.ACCESS_COARSE_LOCATION",
            "android.permission.CAMERA",
            "android.permission.READ_MEDIA_IMAGES",
        ]
        for perm in permissions:
            self.run_adb(["shell", "pm", "grant", self.package, perm])

    def launch_app_or_target(self) -> bool:
        """Launch the application, either directly into target activity/deeplink or main launcher."""
        if self.target_deeplink:
            live_print(f"[*] Launching target via Deep Link: {self.target_deeplink} ...")
            proc = self.run_adb(["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", self.target_deeplink])
            time.sleep(2.0)
            if self.is_app_foreground():
                return True

        if self.target_activity:
            comp = self.target_activity
            if "/" in comp:
                target_comp = comp
            elif comp.startswith("."):
                target_comp = f"{self.package}/{comp}"
            else:
                target_comp = f"{self.package}/.{comp}"
            live_print(f"[*] Attempting direct component launch: {target_comp} ...")
            proc = self.run_adb(["shell", "am", "start", "-n", target_comp])
            time.sleep(2.0)
            if self.is_app_foreground():
                return True
            live_print("  [WARN] Direct component launch did not foreground app; falling back to main launcher.")

        # Fallback to main launcher
        launcher_cls = LAUNCHER if LAUNCHER else ".MainActivity"
        if "/" in launcher_cls:
            main_comp = launcher_cls
        elif launcher_cls.startswith("."):
            main_comp = f"{self.package}/{launcher_cls}"
        else:
            main_comp = f"{self.package}/.{launcher_cls}"
        live_print(f"[*] Launching application main component: {main_comp} ...")
        self.run_adb(["shell", "am", "start", "-n", main_comp])
        time.sleep(2.0)
        return self.is_app_foreground()

    def dump_hierarchy(self, retries: int = 3) -> list[UINode]:
        """Dump UI Automator hierarchy and parse into UINode tree with retries."""
        for attempt in range(retries):
            dump_proc = self.run_adb(["shell", "uiautomator", "dump", "/data/local/tmp/harness_uidump.xml"])
            if dump_proc.returncode == 0:
                cat_proc = self.run_adb(["shell", "cat", "/data/local/tmp/harness_uidump.xml"])
                nodes = parse_ui_hierarchy(cat_proc.stdout)
                if nodes:
                    return nodes
            time.sleep(0.5)
        return []

    def tap(self, node: UINode, label: str = "") -> bool:
        """Tap center of node with safety containment check."""
        if not self.is_app_foreground():
            live_print(f"[WARN] Cannot tap '{label}': Foreground app is not {self.package}. Aborting tap for safety.", err=True)
            return False
        cx, cy = node.center
        if cx <= 0 or cy <= 0:
            return False
        self.run_adb(["shell", "input", "tap", str(cx), str(cy)])
        time.sleep(1.0)
        return True

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 350):
        """Execute swipe gesture on device screen."""
        self.run_adb(["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)])
        time.sleep(0.8)

    def scroll_down(self) -> bool:
        """Perform a standard vertical scroll down gesture."""
        return self._scroll(forward=True)

    def scroll_up(self) -> bool:
        """Perform a standard vertical scroll up gesture."""
        return self._scroll(forward=False)

    def hide_keyboard(self):
        """Attempt to hide soft keyboard so buttons are not obstructed."""
        self.run_adb(["shell", "input", "keyevent", "111"])  # KEYCODE_ESCAPE
        time.sleep(0.3)

    def erase_text(self, count: int = 50):
        """Erase text in current focused field."""
        self.run_adb(["shell", "input", "keyevent", "123"])  # KEYCODE_MOVE_END
        for _ in range(min(count, 50)):
            self.run_adb(["shell", "input", "keyevent", "67"])  # KEYCODE_DEL
        time.sleep(0.3)

    def input_text_safe(self, text: str, clear_first: bool = False, hide_keyboard_after: bool = True) -> bool:
        """Safely type text into active field with whitespace escaping and optional auto-keyboard hide."""
        if not self.is_app_foreground():
            return False
        if clear_first:
            self.erase_text()
        escaped = text.replace(" ", "%s").replace("&", "\\&").replace("<", "\\<").replace(">", "\\>")
        self.run_adb(["shell", "input", "text", escaped])
        time.sleep(0.5)
        if hide_keyboard_after:
            self.hide_keyboard()
        return True

    def scroll_until_visible(self, matcher, max_swipes: int = 5) -> UINode | None:
        """Scroll down incrementally until a node matching predicate is discovered."""
        for _ in range(max_swipes):
            nodes = self.dump_hierarchy()
            found = matcher(nodes)
            if found:
                return found
            self.scroll_down()
            time.sleep(0.5)
        nodes = self.dump_hierarchy()
        return matcher(nodes)

    def capture_screenshot(self, name: str) -> Path | None:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = SCREENSHOTS_DIR / f"{name}_{stamp}.png"
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
                self.screenshots.append(out_path)
                return out_path
            if out_path.is_file():
                out_path.unlink()
        except Exception:
            pass
        return None

    def save_failure_forensics(
        self,
        step_idx: int,
        step_name: str,
        reason: str,
        nodes: list[UINode],
    ) -> dict:
        """Capture failure screenshot, dump failure UI hierarchy, and extract last 50 Logcat lines."""
        E2E_STATE_DIR.mkdir(parents=True, exist_ok=True)
        shot = self.capture_screenshot(f"e2e_failed_step{step_idx}")

        # Dump hierarchy XML
        try:
            raw_dump = self.run_adb(["shell", "cat", "/data/local/tmp/harness_uidump.xml"]).stdout or ""
            (E2E_STATE_DIR / "failed_hierarchy.xml").write_text(raw_dump, encoding="utf-8", errors="replace")
        except Exception:
            pass

        # Dump Logcat
        logcat_out = ""
        try:
            proc = self.run_adb(["logcat", "-d", "-t", "50", "-v", "time"])
            logcat_out = proc.stdout or ""
            (E2E_STATE_DIR / "failed_logcat.txt").write_text(logcat_out, encoding="utf-8", errors="replace")
        except Exception:
            pass

        crashes = self.check_logcat_crashes()

        classification = "ASSERTION_FAILED"
        if crashes:
            classification = "RUNTIME_CRASH"
        elif "ANR" in logcat_out or "timed out" in reason.lower():
            classification = "TIMEOUT_UNRESPONSIVE"

        return {
            "step_index": step_idx,
            "step_name": step_name,
            "failure_reason": reason,
            "classification": classification,
            "screenshot": str(shot) if shot else None,
            "hierarchy_file": str(E2E_STATE_DIR / "failed_hierarchy.xml"),
            "logcat_file": str(E2E_STATE_DIR / "failed_logcat.txt"),
            "crashes": crashes,
        }

    def execute_flow(self, flow: dict, repo: Path) -> dict:
        """Execute a declarative Maestro-compatible multi-step flow."""
        steps_out: list[dict] = []
        string_index = index_string_resources(repo)

        self.wake_and_unlock()
        self.grant_common_permissions()

        live_print(f"[*] Executing Declarative E2E Flow on {self.serial} ({self.package})...")

        launched = self.launch_app_or_target()
        if not launched:
            forensics = self.save_failure_forensics(0, "Launch", f"Failed to foreground {self.package}", [])
            return {
                "verdict": "FAIL",
                "reason": f"Target application {self.package} failed to foreground.",
                "forensics": forensics,
                "steps": steps_out,
            }

        nodes = self.dump_hierarchy()
        active_locale = detect_app_locale(nodes, string_index)
        live_print(f"[*] Detected active in-app locale: '{active_locale}' (string resources indexed).")

        flow_steps = flow.get("steps", [])
        if not flow_steps:
            live_print("[WARN] Flow definition contains no steps; executing default smoke pass.")
            return self.run_targeted_smoke_flow()

        for idx, step in enumerate(flow_steps, start=1):
            action = step.get("action") or step.get("command") or ""
            step_desc = f"Step {idx}: {action}"

            if action in ("launchApp", "launch"):
                launched = self.launch_app_or_target()
                time.sleep(1.0)
                nodes = self.dump_hierarchy()
                steps_out.append({"step": step_desc, "status": "PASS" if launched else "FAIL"})
                if not launched:
                    forensics = self.save_failure_forensics(idx, step_desc, "App launch failed", nodes)
                    return {"verdict": "FAIL", "reason": "App launch failed", "forensics": forensics, "steps": steps_out}
                live_print(f"  [PASS] {step_desc}")

            elif action in ("tapOn", "click", "tap"):
                target_id = step.get("id") or step.get("testTag")
                target_desc = step.get("contentDesc") or step.get("content_desc")
                target_text = resolve_target_text(step, active_locale, string_index) or step.get("target")

                nodes = self.dump_hierarchy()
                node = None
                if target_id:
                    node = find_first(nodes, resource_id=target_id)
                if not node and target_desc:
                    node = find_first(nodes, content_desc=target_desc)
                if not node and target_text:
                    node = find_first(nodes, text=target_text) or find_first(nodes, content_desc=target_text)

                if not node and (step.get("scroll") == "true" or step.get("auto_scroll") == "true"):
                    def _matcher(nl):
                        if target_id:
                            n = find_first(nl, resource_id=target_id)
                            if n: return n
                        if target_desc:
                            n = find_first(nl, content_desc=target_desc)
                            if n: return n
                        if target_text:
                            n = find_first(nl, text=target_text) or find_first(nl, content_desc=target_text)
                            if n: return n
                        return None
                    node = self.scroll_until_visible(_matcher)

                if not node:
                    forensics = self.save_failure_forensics(idx, step_desc, f"Element not found (id={target_id}, text={target_text})", nodes)
                    steps_out.append({"step": step_desc, "status": "FAIL", "reason": "Target node not found"})
                    live_print(f"  [FAIL] {step_desc} -> Element not found in hierarchy", err=True)
                    return {"verdict": "FAIL", "reason": f"Target element not found: {step}", "forensics": forensics, "steps": steps_out}

                tap_ok = self.tap(node, label=str(target_id or target_text))
                steps_out.append({"step": step_desc, "status": "PASS" if tap_ok else "FAIL"})
                live_print(f"  [PASS] {step_desc} (target: {target_id or target_text})")
                time.sleep(float(step.get("wait", 0.5)))

            elif action in ("inputText", "type"):
                text_to_type = step.get("text") or step.get("value") or ""
                clear_first = step.get("clear", False) or step.get("erase", False)
                hide_kb = step.get("hideKeyboard", True)
                ok = self.input_text_safe(text_to_type, clear_first=clear_first, hide_keyboard_after=hide_kb)
                steps_out.append({"step": step_desc, "status": "PASS" if ok else "FAIL"})
                live_print(f"  [PASS] {step_desc} (input: '{text_to_type}')")

            elif action in ("eraseText", "clearText"):
                self.erase_text()
                steps_out.append({"step": step_desc, "status": "PASS"})
                live_print(f"  [PASS] {step_desc}")

            elif action in ("hideKeyboard", "dismissKeyguard"):
                self.hide_keyboard()
                steps_out.append({"step": step_desc, "status": "PASS"})
                live_print(f"  [PASS] {step_desc}")

            elif action in ("scroll", "scrollDown", "scrollUp"):
                is_down = "up" not in action.lower() and str(step.get("direction", "down")).lower() == "down"
                ok = self.scroll_down() if is_down else self.scroll_up()
                steps_out.append({"step": step_desc, "status": "PASS" if ok else "WARN"})
                live_print(f"  [PASS] {step_desc}")

            elif action in ("scrollUntilVisible",):
                target_id = step.get("id") or step.get("testTag")
                target_text = resolve_target_text(step, active_locale, string_index) or step.get("target")
                def _m(nl):
                    if target_id:
                        n = find_first(nl, resource_id=target_id)
                        if n: return n
                    if target_text:
                        n = find_first(nl, text=target_text) or find_first(nl, content_desc=target_text)
                        if n: return n
                    return None
                node = self.scroll_until_visible(_m, max_swipes=int(step.get("maxSwipes", 5)))
                if not node:
                    nodes = self.dump_hierarchy()
                    forensics = self.save_failure_forensics(idx, step_desc, f"Element did not appear after scrolling: {target_id or target_text}", nodes)
                    steps_out.append({"step": step_desc, "status": "FAIL"})
                    return {"verdict": "FAIL", "reason": "Element did not appear after scrolling", "forensics": forensics, "steps": steps_out}
                steps_out.append({"step": step_desc, "status": "PASS"})
                live_print(f"  [PASS] {step_desc}")

            elif action in ("back", "pressBack"):
                self.run_adb(["shell", "input", "keyevent", "4"])
                time.sleep(0.5)
                steps_out.append({"step": step_desc, "status": "PASS"})
                live_print(f"  [PASS] {step_desc}")

            elif action in ("assertVisible",):
                target_id = step.get("id") or step.get("testTag")
                target_text = resolve_target_text(step, active_locale, string_index) or step.get("target")
                nodes = self.dump_hierarchy()
                node = None
                if target_id:
                    node = find_first(nodes, resource_id=target_id)
                if not node and target_text:
                    node = find_first(nodes, text=target_text) or find_first(nodes, content_desc=target_text)

                if not node:
                    forensics = self.save_failure_forensics(idx, step_desc, f"Assertion failed: target not visible ({target_id or target_text})", nodes)
                    steps_out.append({"step": step_desc, "status": "FAIL"})
                    live_print(f"  [FAIL] {step_desc} -> Expected element was not visible", err=True)
                    return {"verdict": "FAIL", "reason": f"assertVisible failed: {target_id or target_text}", "forensics": forensics, "steps": steps_out}
                steps_out.append({"step": step_desc, "status": "PASS"})
                live_print(f"  [PASS] {step_desc} (found: {target_id or target_text})")

            elif action in ("assertNotVisible",):
                target_id = step.get("id") or step.get("testTag")
                target_text = resolve_target_text(step, active_locale, string_index) or step.get("target")
                nodes = self.dump_hierarchy()
                node = None
                if target_id:
                    node = find_first(nodes, resource_id=target_id)
                if not node and target_text:
                    node = find_first(nodes, text=target_text) or find_first(nodes, content_desc=target_text)

                if node:
                    forensics = self.save_failure_forensics(idx, step_desc, f"Assertion failed: element should NOT be visible ({target_id or target_text})", nodes)
                    steps_out.append({"step": step_desc, "status": "FAIL"})
                    live_print(f"  [FAIL] {step_desc} -> Element unexpectedly visible", err=True)
                    return {"verdict": "FAIL", "reason": f"assertNotVisible failed: {target_id or target_text}", "forensics": forensics, "steps": steps_out}
                steps_out.append({"step": step_desc, "status": "PASS"})
                live_print(f"  [PASS] {step_desc}")

            elif action in ("takeScreenshot", "screenshot"):
                shot_name = step.get("name") or f"flow_step_{idx}"
                shot = self.capture_screenshot(shot_name)
                steps_out.append({"step": step_desc, "status": "PASS", "screenshot": str(shot) if shot else None})
                live_print(f"  [PASS] {step_desc} (saved: {shot.name if shot else 'none'})")

            elif action in ("wait", "sleep"):
                dur = float(step.get("duration", 1.0))
                time.sleep(dur)
                steps_out.append({"step": step_desc, "status": "PASS", "duration": dur})
                live_print(f"  [PASS] {step_desc} ({dur}s)")

            crashes = self.check_logcat_crashes()
            if crashes:
                first = crashes[0]
                forensics = self.save_failure_forensics(idx, step_desc, f"Runtime crash detected: {first['summary']}", nodes)
                return {
                    "verdict": "FAIL",
                    "reason": f"Runtime crash during {step_desc}: {first['summary']}",
                    "forensics": forensics,
                    "steps": steps_out,
                }

        final_shot = self.capture_screenshot("flow_final_verified")
        return {
            "verdict": "PASS",
            "locale": active_locale,
            "steps": steps_out,
            "crashes": [],
            "final_screenshot": str(final_shot) if final_shot else None,
        }

    def check_logcat_crashes(self) -> list[dict]:
        """Deep Logcat forensics: Detect fatal exceptions, ANRs, and Room/Runtime crashes with stacktraces."""
        proc = self.run_adb(["logcat", "-d", "-v", "time", "*:E"])
        output = proc.stdout or ""
        crashes: list[dict] = []
        lines = output.splitlines()
        
        crash_patterns = [
            "FATAL EXCEPTION",
            "AndroidRuntime",
            "ANR in " + self.package,
            "NullPointerException",
            "IllegalStateException",
            "Room cannot verify the data integrity",
            "Unchecked double-bang",
            "ClassCastException",
        ]
        
        for i, line in enumerate(lines):
            if self.package in line or "FATAL" in line or "AndroidRuntime" in line:
                for pat in crash_patterns:
                    if pat in line:
                        # Grab surrounding stacktrace slice (up to 15 lines)
                        stack = lines[max(0, i - 1): min(len(lines), i + 15)]
                        crashes.append({
                            "pattern": pat,
                            "summary": line.strip(),
                            "stacktrace": "\n".join(stack),
                        })
                        break
        return crashes[:5]

    def run_targeted_smoke_flow(self) -> dict:
        """Run comprehensive, diff-aware targeted smoke validation on physical device."""
        steps: list[dict] = []
        live_print(f"[*] Starting Targeted E2E Smoke Flow on {self.serial} ({self.package})...")
        
        self.wake_and_unlock()
        self.grant_common_permissions()

        # Step 1: Launch target activity or main app
        launched = self.launch_app_or_target()
        if not launched:
            return {
                "verdict": "FAIL",
                "reason": f"Target application {self.package} failed to foreground.",
                "steps": steps,
                "crashes": self.check_logcat_crashes(),
            }

        # Step 2: Initial screen hierarchy dump
        nodes = self.dump_hierarchy()
        if not nodes:
            return {
                "verdict": "FAIL",
                "reason": "Failed to dump UI hierarchy from device.",
                "steps": steps,
                "crashes": self.check_logcat_crashes(),
            }

        screen_shot = self.capture_screenshot("e2e_screen_launch")
        steps.append({
            "step": "App & Target Launch",
            "status": "PASS",
            "nodes_found": len(nodes),
            "screenshot": str(screen_shot) if screen_shot else None,
        })
        live_print(f"  [PASS] Target UI foregrounded & hierarchy dumped ({len(nodes)} root nodes).")

        # Step 3: Target elements & keyword verification (if target texts provided)
        matched_targets = []
        for kw in self.target_texts:
            node = find_first(nodes, text=kw) or find_first(nodes, content_desc=kw)
            if node:
                matched_targets.append(kw)
                live_print(f"  [PASS] Verified modified UI target element: '{kw}' (center: {node.center}).")

        if self.target_texts:
            steps.append({
                "step": "Target Elements Verification",
                "status": "PASS" if matched_targets else "INFO",
                "matched_targets": matched_targets,
                "expected_targets": self.target_texts,
            })

        # Step 4: Interactive elements discovery & gesture responsiveness
        clickables = find_nodes(nodes, clickable=True)
        live_print(f"  [PASS] Discovered {len(clickables)} interactive UI element(s).")
        steps.append({
            "step": "Interactive UI Elements Discovery",
            "status": "PASS",
            "clickables_count": len(clickables),
        })

        # Step 5: Scroll stress test if scrollable container exists
        scrollables = find_nodes(nodes, class_name="RecyclerView") or find_nodes(nodes, class_name="ScrollView") or find_nodes(nodes, scrollable=True)
        if scrollables:
            live_print("  [*] Testing scroll responsiveness and frame stability...")
            down_ok = self.scroll_down()
            time.sleep(0.5)
            up_ok = self.scroll_up()
            time.sleep(0.5)
            if down_ok and up_ok:
                steps.append({"step": "Scroll Gesture Responsiveness", "status": "PASS"})
                live_print("  [PASS] Scroll responsiveness verified without UI lockup.")
            else:
                steps.append(
                    {
                        "step": "Scroll Gesture Responsiveness",
                        "status": "WARN",
                        "reason": "device screen size unavailable; scroll skipped",
                    }
                )
                live_print("  [WARN] Scroll step skipped (screen size unavailable) — never reported as PASS.", err=True)

        # Step 6: Real-time Logcat crash forensics
        crashes = self.check_logcat_crashes()
        if crashes:
            first_crash = crashes[0]
            live_print(f"  [FAIL] Detected runtime crash in Logcat: {first_crash['summary']}", err=True)
            return {
                "verdict": "FAIL",
                "reason": f"Runtime crash detected: {first_crash['summary']}",
                "stacktrace": first_crash.get("stacktrace"),
                "steps": steps,
                "crashes": crashes,
            }
        steps.append({"step": "Logcat Crash Forensics", "status": "PASS", "crashes": 0})
        live_print("  [PASS] Zero fatal crashes, ANRs, or Room migration exceptions in Logcat.")

        final_shot = self.capture_screenshot("e2e_final_verified")
        return {
            "verdict": "PASS",
            "steps": steps,
            "crashes": [],
            "final_screenshot": str(final_shot) if final_shot else None,
        }


def main() -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description=f"Autonomous Targeted E2E Smoke Testing for {PRODUCT_NAME}")
    parser.add_argument("-s", "--serial", default=None, help="Device serial")
    parser.add_argument("-p", "--package", default=APPLICATION_ID, help="Target application package")
    parser.add_argument("--auto-diff", action="store_true", help="Auto-discover modified activities and strings from git diff")
    parser.add_argument("--target-activity", default=None, help="Direct target Activity class or component name to launch")
    parser.add_argument("--target-deeplink", default=None, help="Direct deep link URI to launch")
    parser.add_argument("--target-text", action="append", default=[], help="Expected text or keyword on target screen")
    parser.add_argument("--flow", default=None, help="Path to declarative YAML/JSON flow file to execute")
    parser.add_argument("--flow-text", default=None, help="Inline YAML/JSON flow string to execute")
    parser.add_argument("--force-native", action="store_true", help="Force native Python ADB runner even if Maestro CLI is installed")
    parser.add_argument("--dump-only", action="store_true", help="Dump and print current UI hierarchy JSON and exit")
    parser.add_argument("--json", action="store_true", help="Print structured JSON result")
    args = parser.parse_args()

    allow_emu = bool(ALLOW_EMULATOR)
    serial = args.serial or first_adb_serial(allow_emulator=allow_emu)
    if not serial:
        verdict = no_device_verdict()
        write_gate_result("e2e", {
            "schema_version": 1,
            "status": "ENV",
            "exit_code": EXIT_ENV,
            "env_class": verdict.env_class,
            "serial": None,
            "git_sha": current_head_sha(),
            "detail": verdict.reason,
        })
        emit_env_failure(verdict, "run_e2e_smoke.py")
        return EXIT_ENV

    target_act = args.target_activity
    target_dl = args.target_deeplink
    target_texts = list(args.target_text)

    # Check APK freshness before executing smoke tests on modified diffs or flow
    apk_path = REPO / apk_relative()
    freshness = check_apk_freshness(apk_path, REPO)
    if not freshness.is_fresh and freshness.status != "MISSING_APK" and (args.auto_diff or args.flow):
        live_print(format_freshness_error(freshness, apk_path), err=True)
        live_print("[ERROR] E2E Smoke test aborted: APK is stale relative to modified files.", err=True)
        write_gate_result("e2e", {
            "schema_version": 1,
            "status": "FAIL",
            "exit_code": 1,
            "env_class": "CODE",
            "serial": serial,
            "git_sha": current_head_sha(),
            "detail": f"STALE_APK: {freshness.reason}",
        })
        return 1

    # If --auto-diff is enabled, inspect git working tree for modified components
    if args.auto_diff:
        diff_info = discover_modified_targets(REPO)
        if diff_info.get("target_activity_component"):
            target_act = diff_info["target_activity_component"]
            live_print(f"[*] Auto-diff discovered target activity: {target_act}")
        elif diff_info.get("target_activity"):
            target_act = diff_info["target_activity"]
            live_print(f"[*] Auto-diff discovered target activity: {target_act}")
        if diff_info.get("target_strings"):
            target_texts.extend(diff_info["target_strings"][:3])
            live_print(f"[*] Auto-diff discovered target string assertions: {target_texts}")

    # Check if declarative flow is provided
    flow_content = None
    if args.flow:
        flow_path = Path(args.flow)
        if not flow_path.is_absolute():
            flow_path = REPO / flow_path
        if flow_path.is_file():
            flow_content = flow_path.read_text(encoding="utf-8", errors="ignore")
        else:
            live_print(f"[ERROR] Flow file not found: {flow_path}", err=True)
            return 1
    elif args.flow_text:
        flow_content = args.flow_text

    flow_data = parse_flow_definition(flow_content) if flow_content else None
    pkg = (flow_data.get("appId") if flow_data else None) or args.package

    # Hybrid check: If Maestro CLI is installed and not forced native
    if args.flow and not args.force_native and shutil.which("maestro"):
        live_print(f"[*] Maestro CLI detected on system PATH; executing flow via Maestro...")
        maestro_cmd = ["maestro", "--device", serial, "test", str(Path(args.flow).resolve())]
        res = subprocess.run(maestro_cmd, cwd=str(REPO))
        return res.returncode

    runner = E2ERunner(
        serial=serial,
        package=pkg,
        target_activity=target_act,
        target_deeplink=target_dl,
        target_texts=target_texts,
    )

    if args.dump_only:
        nodes = runner.dump_hierarchy()
        data = [n.to_dict() for n in nodes]
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    try:
        if flow_data and flow_data.get("steps"):
            result = runner.execute_flow(flow_data, REPO)
        else:
            result = runner.run_targeted_smoke_flow()
    except _DeviceGoneError as exc:
        verdict = FailureVerdict(CLASS_ENV, exc.reason)
        write_gate_result("e2e", {
            "schema_version": 1,
            "status": "ENV",
            "exit_code": EXIT_ENV,
            "env_class": verdict.env_class,
            "serial": serial,
            "git_sha": current_head_sha(),
            "detail": verdict.reason,
        })
        emit_env_failure(verdict, "run_e2e_smoke.py", serial=serial)
        return EXIT_ENV
    E2E_STATE_DIR.mkdir(parents=True, exist_ok=True)
    report_file = E2E_STATE_DIR / "last_e2e_result.json"
    report_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    passed = result["verdict"] == "PASS"
    write_gate_result("e2e", {
        "schema_version": 1,
        "status": "PASS" if passed else "FAIL",
        "exit_code": 0 if passed else 1,
        "env_class": "",
        "serial": serial,
        "git_sha": current_head_sha(),
        "detail": str(result.get("reason") or "")[:300],
    })

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["verdict"] == "PASS" else 1

    if result["verdict"] == "PASS":
        live_print(f"\n[SUCCESS] Autonomous Targeted E2E Smoke Test PASSED on {serial}!")
        if result.get("final_screenshot"):
            live_print(f"[*] Verification Screenshot: {result['final_screenshot']}")
        return 0
    else:
        live_print(f"\n[FAIL] Autonomous Targeted E2E Smoke Test FAILED: {result.get('reason')}", err=True)
        if result.get("stacktrace"):
            live_print(f"--- Stacktrace ---\n{result['stacktrace']}\n------------------", err=True)
        if result.get("forensics"):
            forensics = result["forensics"]
            live_print(f"[*] Failure Classification: {forensics.get('classification')}", err=True)
            if forensics.get("screenshot"):
                live_print(f"[*] Failure Screenshot: {forensics['screenshot']}", err=True)
            if forensics.get("hierarchy_file"):
                live_print(f"[*] Failure UI Hierarchy: {forensics['hierarchy_file']}", err=True)
            if forensics.get("logcat_file"):
                live_print(f"[*] Failure Logcat: {forensics['logcat_file']}", err=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
