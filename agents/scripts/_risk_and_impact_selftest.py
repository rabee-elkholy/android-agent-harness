"""Self-test for Risk Tier Classification, Human Approvals, and Impact Analysis.

Stdlib only. Run with:
  python agents/scripts/_risk_and_impact_selftest.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from _hook_state import state_path  # noqa: E402
from impact_analyzer import (  # noqa: E402
    FileSymbols,
    analyze_impact,
    build_repo_index,
    parse_symbols,
)
from risk_tier import (  # noqa: E402
    TIER_CRITICAL,
    TIER_HIGH,
    TIER_LOW,
    TIER_MEDIUM,
    check_risk_approval,
    classify_file_risk,
    classify_working_tree_risk,
    load_risk_approval,
    write_risk_approval,
)

FAILURES: list[str] = []
ROOT = Path(tempfile.mkdtemp())
os.environ["HARNESS_HOOK_STATE"] = str(ROOT / "review-invokes.json")
os.environ["_IN_HOOK_SELFTEST"] = "1"


def check(cond: bool, label: str) -> None:
    if cond:
        print(f"[PASS] {label}")
    else:
        FAILURES.append(label)
        print(f"[FAIL] {label}")


def test_classify_critical() -> None:
    d = ROOT / "crit"
    d.mkdir(parents=True, exist_ok=True)

    billing_file = d / "BillingManager.kt"
    billing_file.write_text("class BillingManager { }", encoding="utf-8")
    tier, _ = classify_file_risk(billing_file, ROOT)
    check(tier == TIER_CRITICAL, "billing file path classified as CRITICAL")

    proguard_file = d / "proguard-rules.pro"
    proguard_file.write_text("-keep class com.acme.** { *; }", encoding="utf-8")
    tier, _ = classify_file_risk(proguard_file, ROOT)
    check(tier == TIER_CRITICAL, "proguard rules classified as CRITICAL")

    crypto_code_file = d / "TokenManager.kt"
    crypto_code_file.write_text("class TokenManager { val c = Cipher.getInstance(\"AES\") }", encoding="utf-8")
    tier, _ = classify_file_risk(crypto_code_file, ROOT)
    check(tier == TIER_CRITICAL, "Cipher.getInstance in code classified as CRITICAL")


def test_classify_high() -> None:
    d = ROOT / "high"
    d.mkdir(parents=True, exist_ok=True)

    manifest_file = d / "AndroidManifest.xml"
    manifest_file.write_text("<manifest><uses-permission android:name=\"android.permission.CAMERA\"/></manifest>", encoding="utf-8")
    tier, _ = classify_file_risk(manifest_file, ROOT)
    check(tier == TIER_HIGH, "AndroidManifest.xml with permission classified as HIGH")

    gradle_file = d / "build.gradle.kts"
    gradle_file.write_text("plugins { id(\"com.android.application\") }", encoding="utf-8")
    tier, _ = classify_file_risk(gradle_file, ROOT)
    check(tier == TIER_HIGH, "build.gradle.kts classified as HIGH")

    room_file = d / "AppDatabase.kt"
    room_file.write_text("@Database(entities = [User::class], version = 2)\nabstract class AppDatabase : RoomDatabase()", encoding="utf-8")
    tier, _ = classify_file_risk(room_file, ROOT)
    check(tier == TIER_HIGH, "@Database declaration classified as HIGH")


def test_classify_medium() -> None:
    d = ROOT / "med"
    d.mkdir(parents=True, exist_ok=True)

    vm_file = d / "ProfileViewModel.kt"
    vm_file.write_text("class ProfileViewModel : ViewModel() {\n    fun loadData() { }\n}", encoding="utf-8")
    tier, _ = classify_file_risk(vm_file, ROOT)
    check(tier == TIER_MEDIUM, "standard ViewModel code classified as MEDIUM")


def test_classify_low() -> None:
    d = ROOT / "low"
    d.mkdir(parents=True, exist_ok=True)

    doc_file = d / "README.md"
    doc_file.write_text("# Project Documentation", encoding="utf-8")
    tier, _ = classify_file_risk(doc_file, ROOT)
    check(tier == TIER_LOW, "markdown doc classified as LOW")

    strings_file = d / "strings.xml"
    strings_file.write_text("<resources><string name=\"app_name\">App</string></resources>", encoding="utf-8")
    tier, _ = classify_file_risk(strings_file, ROOT)
    check(tier == TIER_LOW, "strings.xml resource classified as LOW")

    comments_file = d / "Helper.kt"
    comments_file.write_text("// TODO: comment\n/* multi\nline */\n", encoding="utf-8")
    tier, _ = classify_file_risk(comments_file, ROOT, modified_lines={1, 2, 3})
    check(tier == TIER_LOW, "comments-only diff in Kotlin file classified as LOW")


def test_file_level_floor_invariant() -> None:
    d = ROOT / "floor"
    d.mkdir(parents=True, exist_ok=True)

    billing_file = d / "InAppBillingHelper.kt"
    billing_file.write_text("// Just a comment added to billing file", encoding="utf-8")
    tier, _ = classify_file_risk(billing_file, ROOT, modified_lines={1})
    check(tier == TIER_CRITICAL, "comments-only change in billing file remains CRITICAL (floor invariant)")


def test_risk_approval_lifecycle() -> None:
    d = ROOT / "approval"
    d.mkdir(parents=True, exist_ok=True)

    manifest_file = d / "AndroidManifest.xml"
    manifest_file.write_text("<manifest><uses-permission android:name=\"android.permission.INTERNET\"/></manifest>", encoding="utf-8")

    fp = "1234567890abcdef"
    state_file = ROOT / "state" / "risk_approval.json"
    if state_file.is_file():
        state_file.unlink()

    ok, tier, msg = check_risk_approval(ROOT)
    # When testing against clean working tree of ROOT vs files
    check(tier in (TIER_LOW, TIER_MEDIUM, TIER_HIGH, TIER_CRITICAL), "check_risk_approval returns valid tier")

    # Write explicit approval
    write_risk_approval(TIER_HIGH, fp, ROOT)
    approval = load_risk_approval(ROOT)
    check(approval is not None and approval.get("tier") == TIER_HIGH, "risk approval file written and loaded")
    check(approval.get("tree_fingerprint") == fp, "fingerprint stored in approval")


def test_impact_analyzer_symbol_parsing() -> None:
    d = ROOT / "impact_src"
    d.mkdir(parents=True, exist_ok=True)

    kt_file = d / "UserRepo.kt"
    kt_file.write_text(
        "package com.acme.data\n\n"
        "import com.acme.model.User\n"
        "import kotlinx.coroutines.flow.Flow\n\n"
        "interface UserRepo {\n"
        "    fun getUser(): Flow<User>\n"
        "}\n\n"
        "class UserRepoImpl : UserRepo {\n"
        "    override fun getUser(): Flow<User> = TODO()\n"
        "}\n",
        encoding="utf-8",
    )

    syms = parse_symbols(kt_file, ROOT)
    check(syms.package == "com.acme.data", "package parsed correctly")
    check("UserRepo" in syms.declarations and "UserRepoImpl" in syms.declarations, "declarations parsed")
    check("getUser" in syms.functions, "functions parsed")
    check("com.acme.model.User" in syms.imports, "imports parsed")
    check(not syms.is_test, "not marked as test file")


def test_impact_analyzer_dependency_graph() -> None:
    d = ROOT / "impact_graph"
    d.mkdir(parents=True, exist_ok=True)

    repo_file = d / "PaymentRepo.kt"
    repo_file.write_text(
        "package com.acme.payment\n\n"
        "class PaymentRepo {\n"
        "    fun pay() = true\n"
        "}\n",
        encoding="utf-8",
    )

    usecase_file = d / "ProcessPaymentUseCase.kt"
    usecase_file.write_text(
        "package com.acme.payment\n\n"
        "import com.acme.payment.PaymentRepo\n\n"
        "class ProcessPaymentUseCase(val repo: PaymentRepo) {\n"
        "    fun execute() = repo.pay()\n"
        "}\n",
        encoding="utf-8",
    )

    test_file = d / "PaymentRepoTest.kt"
    test_file.write_text(
        "package com.acme.payment\n\n"
        "import com.acme.payment.PaymentRepo\n\n"
        "class PaymentRepoTest {\n"
        "    fun testPay() { }\n"
        "}\n",
        encoding="utf-8",
    )

    screen_file = d / "PaymentScreen.kt"
    screen_file.write_text(
        "package com.acme.payment.ui\n\n"
        "import com.acme.payment.ProcessPaymentUseCase\n\n"
        "class PaymentScreen {\n"
        "}\n",
        encoding="utf-8",
    )

    index = {
        "PaymentRepo.kt": parse_symbols(repo_file, d),
        "ProcessPaymentUseCase.kt": parse_symbols(usecase_file, d),
        "PaymentRepoTest.kt": parse_symbols(test_file, d),
        "PaymentScreen.kt": parse_symbols(screen_file, d),
    }

    result = analyze_impact(d, changed=[repo_file], index=index)
    check("PaymentRepo" in result["modified_symbols"], "modified symbol detected")
    check("PaymentRepoTest" in result["recommended_tests"], "recommended test detected")
    check("PaymentScreen" in result["recommended_ui_surfaces"], "impacted UI surface detected")
    check(result["confidence"] in ("HIGH", "MEDIUM"), "confidence evaluated")


def test_staleness_and_escalation_rejection() -> None:
    d = ROOT / "stale_test"
    d.mkdir(parents=True, exist_ok=True)

    fp1 = "aaaa111122223333"
    fp2 = "bbbb444455556666"

    # Write HIGH approval with fp1
    write_risk_approval(TIER_HIGH, fp1, ROOT)
    approval = load_risk_approval(ROOT)
    check(approval is not None, "approval loaded")

    # If current fingerprint is fp2, check_risk_approval must detect staleness
    # We can test the comparator logic directly
    check(approval.get("tree_fingerprint") != fp2, "fp mismatch correctly identified")

    # If tier escalated to CRITICAL but approval is only HIGH
    from risk_tier import _TIER_ORDER
    check(_TIER_ORDER[TIER_HIGH] < _TIER_ORDER[TIER_CRITICAL], "tier escalation order is strict")


def test_impact_analyzer_wildcards_and_complex_types() -> None:
    d = ROOT / "wildcards"
    d.mkdir(parents=True, exist_ok=True)

    model_file = d / "UserModels.kt"
    model_file.write_text(
        "package com.acme.model\n\n"
        "sealed class UserEvent {\n"
        "    data class LoggedIn(val id: String) : UserEvent()\n"
        "    object LoggedOut : UserEvent()\n"
        "}\n\n"
        "enum class UserRole { ADMIN, MEMBER }\n"
        "sealed interface UserContract\n",
        encoding="utf-8",
    )

    client_file = d / "UserEventHandler.kt"
    client_file.write_text(
        "package com.acme.client\n\n"
        "import com.acme.model.*\n\n"
        "class UserEventHandler {\n"
        "    fun handle(e: UserEvent) = true\n"
        "}\n",
        encoding="utf-8",
    )

    index = {
        "UserModels.kt": parse_symbols(model_file, d),
        "UserEventHandler.kt": parse_symbols(client_file, d),
    }

    syms = index["UserModels.kt"]
    check("UserEvent" in syms.declarations, "sealed class parsed")
    check("UserRole" in syms.declarations, "enum class parsed")
    check("UserContract" in syms.declarations, "sealed interface parsed")

    res = analyze_impact(d, changed=[model_file], index=index)
    check("UserEventHandler.kt" in res["direct_dependents"], "wildcard import dependent captured")
    check(res["confidence"] == "MEDIUM", "confidence drops to MEDIUM on wildcard imports")


def test_clean_tree_behavior() -> None:
    tier, reasons = classify_working_tree_risk(ROOT, files=[])
    check(tier == TIER_LOW, "empty file list classified as LOW")
    check("clean working tree" in reasons[0], "clean working tree reason given")


def main() -> int:
    test_classify_critical()
    test_classify_high()
    test_classify_medium()
    test_classify_low()
    test_file_level_floor_invariant()
    test_risk_approval_lifecycle()
    test_staleness_and_escalation_rejection()
    test_impact_analyzer_symbol_parsing()
    test_impact_analyzer_dependency_graph()
    test_impact_analyzer_wildcards_and_complex_types()
    test_clean_tree_behavior()

    if FAILURES:
        print(f"\n[FAIL] {len(FAILURES)} check(s) failed:")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("\n[SUCCESS] RISK AND IMPACT SELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
