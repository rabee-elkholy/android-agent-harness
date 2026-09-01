"""Self-test for _adb_core.py pure logic. Stdlib only, no device, no network."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from _adb_core import (  # noqa: E402
    DeviceSession,
    canonicalize_steps,
    detect_app_locale,
    discover_diff_targets,
    find_first,
    find_nodes,
    index_string_resources,
    parse_bounds,
    parse_flow_definition,
    parse_ui_hierarchy,
    resolve_target_text,
    validate_flow,
)

FAILURES: list[str] = []


def check(cond: bool, label: str) -> None:
    if cond:
        print(f"[PASS] {label}")
    else:
        FAILURES.append(label)
        print(f"[FAIL] {label}")


def test_parse_bounds() -> None:
    bounds, center = parse_bounds("[10,20][110,120]")
    check(bounds == (10, 20, 110, 120), "parse_bounds values")
    check(center == (60, 70), "parse_bounds center")


def test_hierarchy_parse_and_find() -> None:
    xml = (
        '<hierarchy><node index="0" text="Save" resource-id="com.app:id/btn_save" '
        'class="android.widget.Button" clickable="true" enabled="true" bounds="[0,0][100,50]">'
        '<node index="0" text="Save &amp; Exit" content-desc="" bounds="[0,0][200,50]"/></node>'
        '<node index="1" text="Cancel" clickable="true" bounds="[0,50][100,100]"/></hierarchy>'
    )
    nodes = parse_ui_hierarchy(xml)
    check(len(nodes) == 2, "hierarchy parsed 2 roots")

    subs = find_nodes(nodes, text="Save")
    check(len(subs) == 2, "substring match finds both Save and Save & Exit")
    exacts = find_nodes(nodes, text="Save", exact=True)
    check(len(exacts) == 1, "exact match finds only 'Save'")

    btn = find_first(nodes, resource_id="btn_save")
    check(btn is not None and btn.clickable, "resource-id suffix match works")


def test_string_index_and_locale() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        for folder, body in (
            ("values", '<string name="app_name">My App</string><string name="save"><b>Save</b></string>'),
            ("values-ar", '<string name="save">حفظ</string><string name="app_name">تطبيقي</string>'),
        ):
            d = repo / "res" / folder
            d.mkdir(parents=True)
            (d / "strings.xml").write_text(body, encoding="utf-8")

        idx = index_string_resources(repo)
        check(idx["default"]["save"] == "Save", "nested tags stripped from default value")
        check(idx["ar"]["save"] == "حفظ", "arabic value indexed")

        xml = '<hierarchy><node text="حفظ" content-desc="" bounds="[0,0][10,10]"/></hierarchy>'
        nodes = parse_ui_hierarchy(xml)
        check(detect_app_locale(nodes, idx) == "ar", "locale fingerprint detects arabic")
        check(resolve_target_text("literal", "ar", idx) == "literal", "literal target passes through")
        check(resolve_target_text({"stringKey": "save"}, "ar", idx) == "حفظ", "stringKey resolves arabic")


def test_flow_parse_yaml() -> None:
    yaml = """appId: com.acme.app
---
- launchApp:
    stopApp: true
- tapOn: "Login"
- inputText:
    text: "user#1"
- assertVisible:
    stringKey: save
- assertNotVisible: "Error"
- wait: 2
"""
    flow = parse_flow_definition(yaml)
    check(flow["appId"] == "com.acme.app", "appId parsed")
    check(len(flow["steps"]) == 6, "six steps parsed")
    check(flow["steps"][0] == {"action": "launchApp", "stopApp": True}, "nested stopApp parsed")
    check(flow["steps"][1]["action"] == "tapOn" and flow["steps"][1]["target"] == "Login", "tapOn target parsed")
    check(flow["steps"][2]["text"] == "user#1", "hash preserved in inputText")


def test_flow_parse_json() -> None:
    import json
    data = {"appId": "com.acme.app", "steps": [{"action": "tapOn", "id": "btn"}]}
    flow = parse_flow_definition(json.dumps(data))
    check(flow["appId"] == "com.acme.app", "json appId")
    check(flow["steps"][0]["id"] == "btn", "json step parsed")


def test_flow_validation() -> None:
    good = parse_flow_definition("- tapOn: x\n- assertVisible: y\n")
    check(validate_flow(good) == [], "known actions validate clean")
    bad = parse_flow_definition("- tappOn: x\n")
    errs = validate_flow(bad)
    check(len(errs) == 1 and "unknown action" in errs[0], "unknown action flagged")


def test_canonicalize() -> None:
    steps = canonicalize_steps([{"action": "click", "target": "x"}, {"action": "sleep", "duration": 1}])
    check(steps[0]["action"] == "tapOn", "click aliased to tapOn")
    check(steps[1]["action"] == "wait", "sleep aliased to wait")


def test_component_build() -> None:
    s = DeviceSession("ser", package="com.acme.app", launcher="com.acme.app/.MainActivity")
    check(s.build_component("com.acme.app.profile.ProfileActivity") == "com.acme.app/com.acme.app.profile.ProfileActivity", "FQCN component correct")
    check(s.build_component("ProfileActivity") == "com.acme.app/.ProfileActivity", "simple name component correct")
    check(s.build_component(".profile.ProfileActivity") == "com.acme.app/.profile.ProfileActivity", "leading-dot component correct")
    check(s.build_component("com.acme.app/.MainActivity") == "com.acme.app/.MainActivity", "already-full component unchanged")


def test_is_ascii() -> None:
    check(DeviceSession._is_ascii("hello world 123"), "ascii detected")
    check(not DeviceSession._is_ascii("مرحبا"), "arabic detected as non-ascii")


def test_horizontal_and_state_actions() -> None:
    yaml = """
- swipeLeft: "Carousel"
- swipeRight: "Banner"
- scrollLeft: true
- scrollRight: true
- assertChecked:
    id: remember_me
    checked: true
- assertSelected:
    id: tab_profile
    selected: false
- setNetwork: "offline"
- network: "online"
"""
    flow = parse_flow_definition(yaml)
    check(len(flow["steps"]) == 8, "8 new actions parsed")
    check(validate_flow(flow) == [], "new actions validate clean without errors")
    canon = canonicalize_steps(flow["steps"])
    check(canon[2]["action"] == "swipeRight", "scrollLeft aliased to swipeRight")
    check(canon[3]["action"] == "swipeLeft", "scrollRight aliased to swipeLeft")
    check(canon[7]["action"] == "setNetwork", "network aliased to setNetwork")


def test_state_assertions_node_filter() -> None:
    xml = (
        '<hierarchy>'
        '<node text="Option 1" checkable="true" checked="true" selected="false" bounds="[0,0][100,50]"/>'
        '<node text="Option 2" checkable="true" checked="false" selected="true" bounds="[0,50][100,100]"/>'
        '</hierarchy>'
    )
    nodes = parse_ui_hierarchy(xml)
    checked_nodes = find_nodes(nodes, checked=True)
    check(len(checked_nodes) == 1 and checked_nodes[0].text == "Option 1", "checked=True filter works")
    unchecked_nodes = find_nodes(nodes, checked=False)
    check(len(unchecked_nodes) == 1 and unchecked_nodes[0].text == "Option 2", "checked=False filter works")
    selected_nodes = find_nodes(nodes, selected=True)
    check(len(selected_nodes) == 1 and selected_nodes[0].text == "Option 2", "selected=True filter works")


def test_diff_discovery_no_git_errors() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "app").mkdir()
        res = discover_diff_targets(repo)
        check(isinstance(res, dict) and "activities" in res, "discover returns shape on empty/non-git dir")


def main() -> int:
    test_parse_bounds()
    test_hierarchy_parse_and_find()
    test_string_index_and_locale()
    test_flow_parse_yaml()
    test_flow_parse_json()
    test_flow_validation()
    test_canonicalize()
    test_component_build()
    test_is_ascii()
    test_horizontal_and_state_actions()
    test_state_assertions_node_filter()
    test_diff_discovery_no_git_errors()
    if FAILURES:
        print(f"\n[FAIL] {len(FAILURES)} check(s) failed:")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("\n[SUCCESS] ADB CORE SELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
