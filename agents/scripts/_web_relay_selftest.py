"""Comprehensive selftest suite for Optional Manual Web-Relay Mode (`web-pack` / `web-apply`).

Verifies all 9 Web-Relay safeguards, edge cases, PreToolUse/Worker/Scout boundaries,
bidirectional switching (`Antigravity <-> Web-Relay`), and 100% zero regression on
Default `Antigravity Only` mode.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
KIT_ROOT = SCRIPTS_DIR.parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _vnext_common import atomic_write_json, canonical_sha256, read_json, utc_now  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed:\n{proc.stderr}\n{proc.stdout}")


class WebRelaySelftest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="web_relay_test_")
        self.root = Path(self._tmp.name).resolve()
        self.repo = self.root / "app-repo"
        self.outbox = self.root / "outbox"
        self.downloads = self.root / "downloads"
        self.repo.mkdir(parents=True)
        self.outbox.mkdir(parents=True)
        self.downloads.mkdir(parents=True)

        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.name", "Web Relay Selftest")
        _git(self.repo, "config", "user.email", "webrelay@example.invalid")
        _git(self.repo, "config", "core.autocrlf", "false")

        # Install `.agents` mirror into fixture repo
        shutil.copytree(
            KIT_ROOT / "agents",
            self.repo / ".agents",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "state", "cache"),
        )
        from lifecycle import ARCHITECTURE_MAJOR, EXCLUDE_BEGIN, EXCLUDE_END, OWNERSHIP_RELATIVE, SCHEMA_VERSION
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "architecture_major": ARCHITECTURE_MAJOR,
            "harness_version": (KIT_ROOT / "agents" / "VERSION").read_text(encoding="utf-8").strip(),
            "installed_at": utc_now(),
            "install_backup": None,
            "latest_backup": None,
            "managed_exclude_block": {"begin": EXCLUDE_BEGIN, "end": EXCLUDE_END},
            "entries": [],
        }
        manifest["ownership_sha256"] = canonical_sha256({k: v for k, v in manifest.items() if k != "ownership_sha256"})
        atomic_write_json(self.repo / OWNERSHIP_RELATIVE, manifest)
        (self.repo / ".gitignore").write_text(".agents/\n.harness-setup/\nlocal.properties\n.env\n", encoding="utf-8")
        ctx_d = self.repo / ".agents" / "project-context"
        ctx_d.mkdir(parents=True, exist_ok=True)
        (ctx_d / "project-notes.md").write_text("# Notes\n- Keep Clean Architecture boundaries strict.\n", encoding="utf-8")

        # Multi-module Android fixture (`:core` + `:app`)
        (self.repo / "settings.gradle.kts").write_text(
            'rootProject.name = "RelayDemo"\ninclude(":core", ":app")\n',
            encoding="utf-8",
        )
        (self.repo / "core" / "src" / "main" / "kotlin" / "com" / "demo" / "core").mkdir(parents=True)
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "demo" / "app").mkdir(parents=True)
        (self.repo / "app" / "src" / "test" / "kotlin" / "com" / "demo" / "app").mkdir(parents=True)
        (self.repo / "app" / "src" / "main" / "res" / "values").mkdir(parents=True)

        (self.repo / "core" / "build.gradle.kts").write_text('plugins { kotlin("jvm") }\n', encoding="utf-8")
        (self.repo / "app" / "build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
        (self.repo / "app" / "src" / "main" / "res" / "values" / "strings.xml").write_text(
            '<resources>\n    <string name="app_name">RelayDemo</string>\n</resources>\n',
            encoding="utf-8",
        )

        # Neighbor contract file (`PriceFormatter.kt`)
        (self.repo / "core" / "src" / "main" / "kotlin" / "com" / "demo" / "core" / "PriceFormatter.kt").write_text(
            "package com.demo.core\n\n"
            "interface PriceFormatter {\n"
            "    fun formatEgp(piastres: Long): String\n"
            "}\n",
            encoding="utf-8",
        )

        # 90-line CRLF file with inline API key to test CRLF preservation, secret vault, and >65% shrinkage guard
        lines = [
            "package com.demo.app",
            "",
            "import com.demo.core.PriceFormatter",
            "",
            "class CheckoutCalculator(private val formatter: PriceFormatter) {",
            '    private val mapsKey = "AIzaSyD1234567890abcdefghijklmnopqrstuv"',
            '    private val gatewayBearer = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secretpayload"',
            "",
            "    fun computeTotal(subtotal: Long, discountPercent: Int): Long {",
            "        if (subtotal <= 0L) return 0L",
            "        val clamped = discountPercent.coerceIn(0, 100)",
            "        val discount = (subtotal * clamped) / 100L",
            "        return subtotal - discount",
            "    }",
            "",
            "    fun renderSummary(subtotal: Long, discountPercent: Int): String {",
            "        val total = computeTotal(subtotal, discountPercent)",
            "        return formatter.formatEgp(total)",
            "    }",
        ]
        for idx in range(1, 72):
            lines.append(f"    fun helperRule{idx}(v: Long): Long = v + {idx}L")
        lines.append("}")
        lines.append("")
        crlf_bytes = "\r\n".join(lines).encode("utf-8")
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "demo" / "app" / "CheckoutCalculator.kt").write_bytes(crlf_bytes)

        # Fake gradlew that fails when `BUG_TRIGGER_FAIL` is present and writes JUnit XML
        gradlew = self.repo / "gradlew"
        gradlew.write_text(
            "#!/bin/sh\n"
            "calc_file=\"app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt\"\n"
            "test_file=\"app/src/test/kotlin/com/demo/app/CheckoutCalculatorTest.kt\"\n"
            "xml_dir=\"app/build/test-results/testDebugUnitTest\"\n"
            "mkdir -p \"$xml_dir\"\n"
            "if [ -f \"$test_file\" ] && grep -q 'EXPECT_ROUNDING_FIX' \"$test_file\" && ! grep -q 'ROUNDING_FIXED' \"$calc_file\"; then\n"
            "  cat > \"$xml_dir/TEST-com.demo.app.CheckoutCalculatorTest.xml\" <<'EOF'\n"
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<testsuite name=\"com.demo.app.CheckoutCalculatorTest\" tests=\"1\" failures=\"1\" errors=\"0\">\n"
            "  <testcase name=\"roundingHalfUpWorks\" classname=\"com.demo.app.CheckoutCalculatorTest\">\n"
            "    <failure message=\"Expected 95 but was 94\">java.lang.AssertionError: Expected 95 but was 94</failure>\n"
            "  </testcase>\n"
            "</testsuite>\n"
            "EOF\n"
            "  echo '> Task :app:testDebugUnitTest FAILED'\n"
            "  echo '* What went wrong:'\n"
            "  echo \"Execution failed for task ':app:testDebugUnitTest'.\"\n"
            "  echo '> There were failing tests. See the report at: file:///tmp/report'\n"
            "  echo 'BUILD FAILED in 1s'\n"
            "  exit 1\n"
            "fi\n"
            "cat > \"$xml_dir/TEST-com.demo.app.CheckoutCalculatorTest.xml\" <<'EOF'\n"
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<testsuite name=\"com.demo.app.CheckoutCalculatorTest\" tests=\"1\" failures=\"0\" errors=\"0\">\n"
            "  <testcase name=\"roundingHalfUpWorks\" classname=\"com.demo.app.CheckoutCalculatorTest\"/>\n"
            "</testsuite>\n"
            "EOF\n"
            "exit 0\n",
            encoding="utf-8",
        )
        gradlew.chmod(gradlew.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        gradlew_bat = self.repo / "gradlew.bat"
        bat_py = (
            "import pathlib, sys\n"
            "calc = pathlib.Path('app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt')\n"
            "test = pathlib.Path('app/src/test/kotlin/com/demo/app/CheckoutCalculatorTest.kt')\n"
            "xml_dir = pathlib.Path('app/build/test-results/testDebugUnitTest')\n"
            "xml_dir.mkdir(parents=True, exist_ok=True)\n"
            "if test.is_file() and 'EXPECT_ROUNDING_FIX' in test.read_text('utf-8') and 'ROUNDING_FIXED' not in calc.read_text('utf-8'):\n"
            "    (xml_dir / 'TEST-com.demo.app.CheckoutCalculatorTest.xml').write_text(\n"
            "        '<?xml version=\"1.0\" encoding=\"UTF-8\"?>\\n'\n"
            "        '<testsuite name=\"com.demo.app.CheckoutCalculatorTest\" tests=\"1\" failures=\"1\" errors=\"0\">\\n'\n"
            "        '  <testcase name=\"roundingHalfUpWorks\" classname=\"com.demo.app.CheckoutCalculatorTest\">\\n'\n"
            "        '    <failure message=\"Expected 95 but was 94\">java.lang.AssertionError: Expected 95 but was 94</failure>\\n'\n"
            "        '  </testcase>\\n</testsuite>\\n', encoding='utf-8')\n"
            "    print('> Task :app:testDebugUnitTest FAILED')\n"
            "    print('* What went wrong:')\n"
            "    print(\"Execution failed for task ':app:testDebugUnitTest'.\")\n"
            "    print('> There were failing tests. See the report at: file:///tmp/report')\n"
            "    print('BUILD FAILED in 1s')\n"
            "    sys.exit(1)\n"
            "(xml_dir / 'TEST-com.demo.app.CheckoutCalculatorTest.xml').write_text(\n"
            "    '<?xml version=\"1.0\" encoding=\"UTF-8\"?>\\n'\n"
            "    '<testsuite name=\"com.demo.app.CheckoutCalculatorTest\" tests=\"1\" failures=\"0\" errors=\"0\">\\n'\n"
            "    '  <testcase name=\"roundingHalfUpWorks\" classname=\"com.demo.app.CheckoutCalculatorTest\"/>\\n'\n"
            "    '</testsuite>\\n', encoding='utf-8')\n"
        )
        import base64
        bat_b64 = base64.b64encode(bat_py.encode("utf-8")).decode("ascii")
        gradlew_bat.write_text(
            f'@echo off\r\n"{sys.executable}" -c "import base64; exec(base64.b64decode(\'{bat_b64}\').decode())"\r\n',
            encoding="utf-8",
        )

        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-qm", "initial fixture")

        # Sensitive files outside git that must NEVER leak into web-pack
        (self.repo / "local.properties").write_text("sdk.dir=/opt/android-sdk\nMAPS_SECRET=super_secret_12345\n", encoding="utf-8")
        (self.repo / ".env").write_text("STRIPE_SECRET=sk-abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")

        self.env = {
            **os.environ,
            "HARNESS_REPO": str(self.repo),
            "HARNESS_WEB_RELAY_OUTBOX": str(self.outbox),
            "HARNESS_WEB_RELAY_DOWNLOADS": str(self.downloads),
            "HARNESS_NO_CLIPBOARD": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
        }

    def tearDown(self) -> None:
        try:
            self._tmp.cleanup()
        except OSError:
            shutil.rmtree(self._tmp.name, ignore_errors=True)

    def _run_harness(self, *args: str, stdin_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.repo / ".agents" / "harness.py"), *args],
            cwd=str(self.repo),
            env=self.env,
            input=stdin_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def test_01_default_antigravity_mode_100_percent_untouched(self) -> None:
        """Mode 1 (Antigravity Only) executes identically with zero web-relay side effects."""
        r_ctx = self._run_harness(
            "task-context",
            "--file",
            "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
            "--json",
        )
        self.assertEqual(0, r_ctx.returncode, r_ctx.stderr)

        r_draft = self._run_harness(
            "task",
            "draft",
            "--task-id",
            "default-mode-01",
            "--outcome",
            "Add tax helper to CheckoutCalculator",
            "--kind",
            "FEATURE",
            "--expected-surfaces",
            "BUSINESS_LOGIC",
            "--expected-modules",
            ":app",
            "--expected-files",
            "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
            "--approach",
            "Add computeTax in CheckoutCalculator",
            "--test-strategy",
            "Policy-selected relevant tests",
            "--device-strategy",
            "Not required for pure logic",
            "--risks",
            "Rounding edge cases",
            "--rollback",
            "Revert CheckoutCalculator.kt",
            "--json",
        )
        self.assertEqual(0, r_draft.returncode, r_draft.stderr)
        draft_data = json.loads(r_draft.stdout)

        r_app = self._run_harness(
            "task",
            "approve",
            "--task-id",
            "default-mode-01",
            "--source",
            "conversation",
            "--proof-reference",
            "Proceed",
            "--enforcement-tier",
            "RULE_ENFORCED",
            "--plan-hash",
            draft_data["plan_sha256"],
            "--json",
        )
        self.assertEqual(0, r_app.returncode, r_app.stderr)

        calc_path = self.repo / "app" / "src" / "main" / "kotlin" / "com" / "demo" / "app" / "CheckoutCalculator.kt"
        calc_path.write_bytes(calc_path.read_bytes().replace(b"helperRule71(v: Long): Long = v + 71L", b"helperRule71(v: Long): Long = v + 72L"))

        r_next = self._run_harness("task", "status", "--task-id", "default-mode-01", "--next", "--brief", "--json")
        self.assertEqual(0, r_next.returncode, r_next.stderr)
        next_obj = json.loads(r_next.stdout)["next_action"]
        self.assertNotIn("web_relay_applied", next_obj)
        self.assertNotIn("Web-Relay", next_obj.get("reason", ""))
        self.assertFalse((self.repo / ".agents" / "state" / "web-relay").exists())

    def test_02_secret_vault_redaction_neighbor_signatures_and_12_file_single_bundle(self) -> None:
        """Safeguards #1, #2, #3: Secret files blocked, inline secrets vaulted, >10 files in 1 .md bundle, NEED_FILES expands."""
        extra_files = []
        for i in range(1, 12):
            rel = f"app/src/main/kotlin/com/demo/app/SlicePart{i}.kt"
            p = self.repo / rel
            p.write_text(f"package com.demo.app\n\nclass SlicePart{i} {{\n    fun id(): Int = {i}\n}}\n", encoding="utf-8")
            extra_files.append(rel)
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-qm", "add 11 slice files")

        pack_cmd = [
            "web-pack",
            "--prompt",
            "Update CheckoutCalculator and SlicePart1..11",
            "--no-clipboard",
            "--file",
            "local.properties",
            "--file",
            ".env",
            "--file",
            "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
            "--json",
        ]
        for ef in extra_files:
            pack_cmd.extend(["--file", ef])

        r_pack = self._run_harness(*pack_cmd)
        self.assertEqual(0, r_pack.returncode, r_pack.stderr)
        pack_info = json.loads(r_pack.stdout)
        self.assertGreaterEqual(len(pack_info["editable_files"]), 12)  # >= 12 > Gemini Web's 10-file ZIP cap!
        self.assertNotIn("local.properties", pack_info["editable_files"])
        self.assertNotIn(".env", pack_info["editable_files"])
        self.assertGreaterEqual(pack_info["redacted_secrets_count"], 2)

        bundle_text = Path(pack_info["bundle_file"]).read_text(encoding="utf-8")
        self.assertNotIn("AIzaSyD1234567890abcdefghijklmnopqrstuv", bundle_text)
        self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secretpayload", bundle_text)
        self.assertIn("__HARNESS_REDACTED_SECRET_1__", bundle_text)
        self.assertIn("READ_ONLY_NEIGHBOR_SIGNATURES", bundle_text)
        self.assertIn("interface PriceFormatter", bundle_text)

        # Test `NEED_FILES` response auto-expands pack without mutating files
        need_payload = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": pack_info["pack_id"],
            "repo_fingerprint": pack_info["repo_fingerprint"],
            "status": "NEED_FILES",
            "needed_files": ["core/src/main/kotlin/com/demo/core/PriceFormatter.kt"],
            "reason": "Need PriceFormatter implementation details",
        }
        need_file = self.downloads / "need_files_reply.json"
        need_file.write_text(json.dumps(need_payload), encoding="utf-8")

        r_need = self._run_harness(
            "web-apply",
            "--file",
            str(need_file),
            "--source",
            "conversation",
            "--proof-reference",
            "apply web reply",
            "--json",
        )
        self.assertEqual(0, r_need.returncode, r_need.stderr)
        need_res = json.loads(r_need.stdout)
        self.assertEqual("NEED_FILES_EXPANDED", need_res["status"])
        self.assertIn("core/src/main/kotlin/com/demo/core/PriceFormatter.kt", need_res["new_pack"]["editable_files"])

    def test_03_anti_truncation_scope_guards_crlf_vault_restore_and_anti_replay(self) -> None:
        """Safeguards #3, #4, #6, #7, #9: Cold-start baseline, anti-truncation, brace check, CRLF, secret restore, anti-replay."""
        # Leave an unrelated dirty file before cold-start to prove baseline preserves preexisting_dirty!
        str_path = self.repo / "app" / "src" / "main" / "res" / "values" / "strings.xml"
        str_path.write_text(
            '<resources>\n    <string name="app_name">RelayDemoDirty</string>\n</resources>\n',
            encoding="utf-8",
        )

        r_pack = self._run_harness(
            "web-pack",
            "--prompt",
            "Add LoyaltyTier.kt and update CheckoutCalculator computeTotal",
            "--file",
            "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
            "--no-clipboard",
            "--json",
        )
        self.assertEqual(0, r_pack.returncode, r_pack.stderr)
        pinfo = json.loads(r_pack.stdout)

        # 3a. Block lazy truncation comment
        bad_trunc = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": pinfo["pack_id"],
            "repo_fingerprint": pinfo["repo_fingerprint"],
            "status": "READY",
            "operations": [
                {
                    "op": "MODIFY",
                    "path": "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
                    "hunks": [
                        {
                            "search": "        return subtotal - discount",
                            "replace": "        // ... rest of code unchanged\n        return subtotal - discount",
                        }
                    ],
                }
            ],
        }
        f_bad = self.downloads / "bad_trunc.json"
        f_bad.write_text(json.dumps(bad_trunc), encoding="utf-8")
        r_bad = self._run_harness("web-apply", "--file", str(f_bad), "--source", "developer_terminal", "--json")
        self.assertEqual(1, r_bad.returncode)
        self.assertIn("LAZY_TRUNCATION_BLOCKED", r_bad.stdout)

        # 3b. Block >65% line wipe on 90-line file
        bad_shrink = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": pinfo["pack_id"],
            "repo_fingerprint": pinfo["repo_fingerprint"],
            "status": "READY",
            "operations": [
                {
                    "op": "MODIFY",
                    "path": "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
                    "content": "package com.demo.app\nclass CheckoutCalculator {\n    fun tiny() = 1\n}\n",
                }
            ],
        }
        f_shrink = self.downloads / "bad_shrink.json"
        f_shrink.write_text(json.dumps(bad_shrink), encoding="utf-8")
        r_shrink = self._run_harness("web-apply", "--file", str(f_shrink), "--source", "developer_terminal", "--json")
        self.assertEqual(1, r_shrink.returncode)
        self.assertIn("SUSPICIOUS_CONTENT_DROP_BLOCKED", r_shrink.stdout)

        # 3c. Block overwriting an existing unscoped file (`PriceFormatter.kt`)
        bad_unscoped = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": pinfo["pack_id"],
            "repo_fingerprint": pinfo["repo_fingerprint"],
            "status": "READY",
            "operations": [
                {
                    "op": "CREATE",
                    "path": "core/src/main/kotlin/com/demo/core/PriceFormatter.kt",
                    "content": "package com.demo.core\ninterface PriceFormatter\n",
                }
            ],
        }
        f_unscoped = self.downloads / "bad_unscoped.json"
        f_unscoped.write_text(json.dumps(bad_unscoped), encoding="utf-8")
        r_unscoped = self._run_harness("web-apply", "--file", str(f_unscoped), "--source", "developer_terminal", "--json")
        self.assertEqual(1, r_unscoped.returncode)
        self.assertIn("UNSCOPED_EXISTING_FILE_OVERWRITE_BLOCKED", r_unscoped.stdout)

        # 3d. Valid apply via Downloads auto-discovery (`f_bad`/`f_shrink`/`f_unscoped` removed; valid `.md` reply placed in Downloads)
        for tmp_f in (f_bad, f_shrink, f_unscoped):
            tmp_f.unlink()

        good_merge = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": pinfo["pack_id"],
            "repo_fingerprint": pinfo["repo_fingerprint"],
            "status": "READY",
            "task_kind": "FEATURE",
            "summary": "Add VIP cap to computeTotal and create LoyaltyTier enum",
            "operations": [
                {
                    "op": "MODIFY",
                    "path": "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
                    "hunks": [
                        {
                            "search": "        return subtotal - discount",
                            "replace": "        val capped = (subtotal - discount).coerceAtLeast(0L)\n        return capped",
                        }
                    ],
                },
                {
                    "op": "CREATE",
                    "path": "app/src/main/kotlin/com/demo/app/LoyaltyTier.kt",
                    "content": "package com.demo.app\n\nenum class LoyaltyTier { STANDARD, GOLD }\n",
                },
            ],
        }
        reply_md = self.downloads / "gemini-web-reply.md"
        reply_md.write_text("Here is the merge payload:\n```json\n" + json.dumps(good_merge, indent=2) + "\n```\n", encoding="utf-8")

        r_ok = self._run_harness(
            "web-apply",
            "--source",
            "conversation",
            "--proof-reference",
            "تمام نفذ الميرج",
            "--json",
        )
        self.assertEqual(0, r_ok.returncode, r_ok.stderr)
        apply_res = json.loads(r_ok.stdout)
        self.assertEqual("APPLIED", apply_res["status"])
        self.assertTrue(str(apply_res["origin"]).startswith("downloads:"))

        # Verify CRLF preserved AND secrets restored byte-for-byte!
        calc_raw = (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "demo" / "app" / "CheckoutCalculator.kt").read_bytes()
        self.assertIn(b"\r\n", calc_raw)
        self.assertIn(b"AIzaSyD1234567890abcdefghijklmnopqrstuv", calc_raw)
        self.assertIn(b"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secretpayload", calc_raw)
        self.assertNotIn(b"__HARNESS_REDACTED_SECRET_", calc_raw)

        # Verify task-baseline.json captured `strings.xml` BEFORE writing Web files!
        tid = apply_res["task_id"]
        baseline = read_json(self.repo / ".agents" / "state" / "tasks" / tid / "task-baseline.json")
        baseline_paths = [c.get("path") for c in (baseline.get("changes") or [])]
        self.assertIn("app/src/main/res/values/strings.xml", baseline_paths)
        self.assertNotIn("app/src/main/kotlin/com/demo/app/LoyaltyTier.kt", baseline_paths)

        # Verify router sees `web-relay-receipt.json` (`Zero Re-Read`)
        r_router = self._run_harness("task", "status", "--task-id", tid, "--next", "--brief", "--json")
        self.assertEqual(0, r_router.returncode, r_router.stderr)
        next_act = json.loads(r_router.stdout)["next_action"]
        self.assertTrue(next_act.get("web_relay_applied"))
        self.assertIn("without re-reading applied files", next_act.get("reason", ""))

        # 3e. Replay of same `pack_id` is blocked!
        r_replay = self._run_harness(
            "web-apply",
            "--source",
            "conversation",
            "--proof-reference",
            "apply again",
            "--json",
        )
        self.assertEqual(1, r_replay.returncode)
        self.assertIn("PACK_ALREADY_APPLIED", r_replay.stdout)

    def test_04_three_way_git_merge_on_concurrent_local_edit(self) -> None:
        """Safeguard #8: Concurrent non-conflicting local edit merges cleanly via 3-way git merge-file."""
        r_pack = self._run_harness(
            "web-pack",
            "--prompt",
            "Update computeTotal in CheckoutCalculator",
            "--file",
            "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
            "--no-clipboard",
            "--json",
        )
        self.assertEqual(0, r_pack.returncode, r_pack.stderr)
        pinfo = json.loads(r_pack.stdout)

        # Simulate developer or `git pull` editing the bottom of CheckoutCalculator.kt AFTER `web-pack`!
        calc_file = self.repo / "app" / "src" / "main" / "kotlin" / "com" / "demo" / "app" / "CheckoutCalculator.kt"
        calc_file.write_bytes(
            calc_file.read_bytes().replace(
                b"fun helperRule70(v: Long): Long = v + 70L",
                b"fun helperRule70(v: Long): Long = v + 7000L",
            )
        )

        # Gemini Web edits the top (`computeTotal`) against the older base_text
        merge_payload = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": pinfo["pack_id"],
            "repo_fingerprint": pinfo["repo_fingerprint"],
            "status": "READY",
            "task_kind": "FEATURE",
            "summary": "Clamp negative discount",
            "operations": [
                {
                    "op": "MODIFY",
                    "path": "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
                    "hunks": [
                        {
                            "search": "        val discount = (subtotal * clamped) / 100L",
                            "replace": "        val discount = ((subtotal * clamped) / 100L).coerceAtLeast(0L)",
                        }
                    ],
                }
            ],
        }
        r_apply = self._run_harness(
            "web-apply",
            "--stdin",
            "--source",
            "developer_terminal",
            "--json",
            stdin_text=json.dumps(merge_payload),
        )
        self.assertEqual(0, r_apply.returncode, r_apply.stderr + "\n" + r_apply.stdout)
        merged_txt = calc_file.read_text(encoding="utf-8")
        self.assertIn("helperRule70(v: Long): Long = v + 7000L", merged_txt)
        self.assertIn("((subtotal * clamped) / 100L).coerceAtLeast(0L)", merged_txt)

    def test_05_bug_auto_red_green_reproduction(self) -> None:
        """Collision #2: Cold-start BUG apply writes test first, captures RED evidence, then writes fix."""
        r_pack = self._run_harness(
            "web-pack",
            "--prompt",
            "Fix half-up rounding bug in CheckoutCalculator",
            "--kind",
            "BUG",
            "--file",
            "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
            "--no-clipboard",
            "--json",
        )
        self.assertEqual(0, r_pack.returncode, r_pack.stderr)
        pinfo = json.loads(r_pack.stdout)

        bug_merge = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": pinfo["pack_id"],
            "repo_fingerprint": pinfo["repo_fingerprint"],
            "status": "READY",
            "task_kind": "BUG",
            "summary": "Add rounding regression test and half-up rounding fix",
            "operations": [
                {
                    "op": "CREATE",
                    "path": "app/src/test/kotlin/com/demo/app/CheckoutCalculatorTest.kt",
                    "content": (
                        "package com.demo.app\n\n"
                        "// EXPECT_ROUNDING_FIX\n"
                        "class CheckoutCalculatorTest {\n"
                        "    fun roundingHalfUpWorks() {}\n"
                        "}\n"
                    ),
                },
                {
                    "op": "MODIFY",
                    "path": "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
                    "hunks": [
                        {
                            "search": "        val discount = (subtotal * clamped) / 100L",
                            "replace": "        // ROUNDING_FIXED\n        val discount = (subtotal * clamped + 50L) / 100L",
                        }
                    ],
                },
            ],
        }
        r_apply = self._run_harness(
            "web-apply",
            "--stdin",
            "--source",
            "conversation",
            "--proof-reference",
            "نفذ اصلاح البج",
            "--json",
            stdin_text=json.dumps(bug_merge),
        )
        self.assertEqual(0, r_apply.returncode, r_apply.stderr + "\n" + r_apply.stdout)
        res = json.loads(r_apply.stdout)
        self.assertTrue(res["auto_red_reproduction"]["attempted"])
        self.assertTrue(res["auto_red_reproduction"]["captured"])
        tid = res["task_id"]
        self.assertTrue((self.repo / ".agents" / "state" / "tasks" / tid / "red-evidence.json").is_file())

    def test_06_multi_phase_staging_and_bidirectional_switching(self) -> None:
        """Collision #3 & Bidirectional Mode Switching: 2-strike handoff -> Web-Relay p1+p2 staging -> Antigravity checkpoint -> p2 apply."""
        self._run_harness(
            "task-context",
            "--file",
            "core/src/main/kotlin/com/demo/core/PriceFormatter.kt",
            "--file",
            "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
            "--json",
        )
        r_draft = self._run_harness(
            "task",
            "draft",
            "--task-id",
            "phased-relay-06",
            "--outcome",
            "Add currency symbol support across :core and :app",
            "--kind",
            "FEATURE",
            "--expected-surfaces",
            "BUSINESS_LOGIC",
            "--expected-modules",
            ":core,:app",
            "--expected-files",
            "core/src/main/kotlin/com/demo/core/PriceFormatter.kt,app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
            "--phases",
            "p1:Extend PriceFormatter in :core,p2:Adopt symbol in :app CheckoutCalculator",
            "--approach",
            "Extend PriceFormatter in p1 and CheckoutCalculator in p2",
            "--test-strategy",
            "Policy-selected relevant tests",
            "--device-strategy",
            "Not required",
            "--risks",
            "Cross-module signature mismatch",
            "--rollback",
            "Revert PriceFormatter and CheckoutCalculator",
            "--json",
        )
        self.assertEqual(0, r_draft.returncode, r_draft.stderr + "\n" + r_draft.stdout)
        draft_doc = json.loads(r_draft.stdout)
        self._run_harness(
            "task",
            "approve",
            "--task-id",
            "phased-relay-06",
            "--source",
            "conversation",
            "--proof-reference",
            "Approve",
            "--enforcement-tier",
            "RULE_ENFORCED",
            "--plan-hash",
            draft_doc["plan_sha256"],
            "--json",
        )

        # Simulate a 2-strike Worker handoff capsule in Mode 1 before switching mid-task to Mode 2!
        tdir = self.repo / ".agents" / "state" / "tasks" / "phased-relay-06"
        atomic_write_json(
            tdir / "worker-handoff.json",
            {"status": "UNRESOLVED", "wave_count": 2, "summary": "Hydrogen High hit cross-module signature question"},
        )

        r_pack = self._run_harness("web-pack", "--task-id", "phased-relay-06", "--no-clipboard", "--json")
        self.assertEqual(0, r_pack.returncode, r_pack.stderr)
        pinfo = json.loads(r_pack.stdout)
        bundle_txt = Path(pinfo["bundle_file"]).read_text(encoding="utf-8")
        self.assertIn("Hydrogen High hit cross-module signature question", bundle_txt)

        # Gemini Web returns edits for BOTH p1 (`PriceFormatter.kt`) and p2 (`CheckoutCalculator.kt`) in one response!
        phased_merge = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": pinfo["pack_id"],
            "repo_fingerprint": pinfo["repo_fingerprint"],
            "task_id": "phased-relay-06",
            "status": "READY",
            "summary": "Implement p1 PriceFormatter default method and p2 CheckoutCalculator usage",
            "operations": [
                {
                    "op": "MODIFY",
                    "path": "core/src/main/kotlin/com/demo/core/PriceFormatter.kt",
                    "hunks": [
                        {
                            "search": "    fun formatEgp(piastres: Long): String",
                            "replace": "    fun formatEgp(piastres: Long): String\n    fun currencyCode(): String = \"EGP\"",
                        }
                    ],
                },
                {
                    "op": "MODIFY",
                    "path": "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
                    "hunks": [
                        {
                            "search": "        return formatter.formatEgp(total)",
                            "replace": "        return formatter.currencyCode() + \" \" + formatter.formatEgp(total)",
                        }
                    ],
                },
            ],
        }
        r_apply_p1 = self._run_harness(
            "web-apply",
            "--stdin",
            "--source",
            "conversation",
            "--proof-reference",
            "طبق المرحلة الاولى",
            "--json",
            stdin_text=json.dumps(phased_merge),
        )
        self.assertEqual(0, r_apply_p1.returncode, r_apply_p1.stderr + "\n" + r_apply_p1.stdout)
        res_p1 = json.loads(r_apply_p1.stdout)
        self.assertEqual(["core/src/main/kotlin/com/demo/core/PriceFormatter.kt"], res_p1["files_written"])
        self.assertIn("p2", res_p1["staged_future_phases"])
        self.assertNotIn("currencyCode()", (self.repo / "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt").read_text(encoding="utf-8"))

        # Advance to p2 in active plan, then apply staged p2 cleanly!
        plan_path = tdir / "plan.json"
        pdoc = read_json(plan_path)
        pdoc["active_phase_index"] = 1
        from plan_authority import save_plan
        save_plan(plan_path, pdoc)

        r_apply_p2 = self._run_harness(
            "web-apply",
            "--staged-phase",
            "--source",
            "conversation",
            "--proof-reference",
            "كمل المرحلة التانية",
            "--json",
        )
        self.assertEqual(0, r_apply_p2.returncode, r_apply_p2.stderr + "\n" + r_apply_p2.stdout)
        res_p2 = json.loads(r_apply_p2.stdout)
        self.assertEqual(["app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt"], res_p2["files_written"])
        self.assertIn("currencyCode()", (self.repo / "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt").read_text(encoding="utf-8"))

    def test_07_pretooluse_scout_and_worker_authority_boundaries(self) -> None:
        """Safeguard #5: PreToolUse blocks unapproved web-apply, allows read-only web-pack, and blocks Worker web-apply."""
        from delegation_policy import _WORKER_FORBIDDEN_LIFECYCLE_RE, scout_command_allowed
        from pre_tool_safety import _developer_authority_violation
        from mutation_guard import _is_read_only

        # Developer authority checks
        self.assertEqual("web-apply", _developer_authority_violation("python .agents/harness.py web-apply"))
        self.assertEqual("web-apply", _developer_authority_violation("python .agents/harness.py web-apply --source developer_terminal"))
        self.assertEqual("web-apply", _developer_authority_violation("python .agents/harness.py web-relay apply --source conversation"))
        self.assertEqual(
            "",
            _developer_authority_violation(
                'python .agents/harness.py web-apply --source conversation --proof-reference "apply merge"'
            ),
        )
        self.assertEqual("", _developer_authority_violation("python .agents/harness.py web-pack --prompt 'fix git merge'"))

        # Read-only & Scout/Worker boundaries
        self.assertTrue(_is_read_only("python .agents/harness.py web-pack --prompt 'hello'", self.repo))
        self.assertTrue(_is_read_only("python .agents/harness.py web-relay status --json", self.repo))
        self.assertFalse(_is_read_only("python .agents/harness.py web-apply --source conversation --proof-reference ok", self.repo))

        self.assertTrue(scout_command_allowed("python .agents/harness.py web-pack --feature Checkout"))
        self.assertTrue(scout_command_allowed("python .agents/harness.py web-relay status --json"))
        self.assertFalse(scout_command_allowed("python .agents/harness.py web-apply --source conversation --proof-reference ok"))

        self.assertIsNotNone(_WORKER_FORBIDDEN_LIFECYCLE_RE.search("python .agents/harness.py web-apply --source conversation --proof-reference ok"))
        self.assertIsNotNone(_WORKER_FORBIDDEN_LIFECYCLE_RE.search("python .agents/scripts/web_relay.py apply --source conversation --proof-reference ok"))

        # End-to-end PreToolUse hook subprocess invocation check
        hook_script = self.repo / ".agents" / "scripts" / "pre_tool_safety.py"
        deny_payload = {
            "conversationId": "conv-relay-check",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "python .agents/harness.py web-apply --source developer_terminal"},
            },
        }
        p_deny = subprocess.run(
            [sys.executable, str(hook_script)],
            cwd=str(self.repo),
            env=self.env,
            input=json.dumps(deny_payload),
            capture_output=True,
            text=True,
            check=False,
        )
        v_deny = json.loads(p_deny.stdout)
        self.assertEqual("deny", v_deny["decision"])

        allow_pack_payload = {
            "conversationId": "conv-relay-check",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": 'python .agents/harness.py web-pack --prompt "Fix zoho and git merge edge case"'},
            },
        }
        p_allow = subprocess.run(
            [sys.executable, str(hook_script)],
            cwd=str(self.repo),
            env=self.env,
            input=json.dumps(allow_pack_payload),
            capture_output=True,
            text=True,
            check=False,
        )
        v_allow = json.loads(p_allow.stdout)
        self.assertEqual("allow", v_allow["decision"], v_allow)

    def test_08_cross_chat_task_bridge_host_continue_and_disjoint_task_switch(self) -> None:
        """Full ecosystem integration: disjoint task switch + Chat 1 web-pack/apply -> task bridge -> Chat 2 staged p2 -> host continue."""
        # Create a disjoint file for Task B so Task A and Task B can coexist via `task switch`
        sibling_rel = "app/src/main/kotlin/com/demo/app/SettingsBadge.kt"
        (self.repo / sibling_rel).write_text("package com.demo.app\n\nclass SettingsBadge { fun label() = \"v1\" }\n", encoding="utf-8")
        _git(self.repo, "add", sibling_rel)
        _git(self.repo, "commit", "-qm", "add sibling file")

        # Draft & approve Task A (`phased-chat-hop`: p1 in :core, p2 in :app)
        self._run_harness(
            "task-context",
            "--file",
            "core/src/main/kotlin/com/demo/core/PriceFormatter.kt",
            "--file",
            "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
            "--file",
            sibling_rel,
            "--json",
        )
        r_da = self._run_harness(
            "task", "draft",
            "--task-id", "phased-chat-hop",
            "--outcome", "Add currency prefix across :core and :app",
            "--kind", "FEATURE",
            "--expected-surfaces", "BUSINESS_LOGIC",
            "--expected-modules", ":core,:app",
            "--expected-files", "core/src/main/kotlin/com/demo/core/PriceFormatter.kt,app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
            "--phases", "p1:Add prefix in :core,p2:Use prefix in :app",
            "--approach", "Add prefix method in p1 and adopt in p2",
            "--test-strategy", "Policy-selected relevant tests",
            "--device-strategy", "Not required",
            "--risks", "Signature sync",
            "--rollback", "Revert both files",
            "--json",
        )
        self.assertEqual(0, r_da.returncode, r_da.stderr)
        da_doc = json.loads(r_da.stdout)
        self._run_harness(
            "task", "approve",
            "--task-id", "phased-chat-hop",
            "--source", "conversation",
            "--proof-reference", "Approve Task A",
            "--enforcement-tier", "RULE_ENFORCED",
            "--plan-hash", da_doc["plan_sha256"],
            "--json",
        )

        # Pack Task A in Chat 1
        r_pa = self._run_harness("web-pack", "--task-id", "phased-chat-hop", "--no-clipboard", "--json")
        self.assertEqual(0, r_pa.returncode, r_pa.stderr)
        pack_a = json.loads(r_pa.stdout)

        # Draft & approve disjoint Task B (`disjoint-sibling`) and switch focus to Task B!
        r_db = self._run_harness(
            "task", "draft",
            "--task-id", "disjoint-sibling",
            "--outcome", "Update SettingsBadge label",
            "--kind", "FEATURE",
            "--expected-surfaces", "BUSINESS_LOGIC",
            "--expected-modules", ":app",
            "--expected-files", sibling_rel,
            "--approach", "Update label()",
            "--test-strategy", "Policy-selected relevant tests",
            "--device-strategy", "Not required",
            "--risks", "None",
            "--rollback", "Revert SettingsBadge.kt",
            "--json",
        )
        self.assertEqual(0, r_db.returncode, r_db.stderr)
        db_doc = json.loads(r_db.stdout)
        self._run_harness(
            "task", "approve",
            "--task-id", "disjoint-sibling",
            "--source", "conversation",
            "--proof-reference", "Approve Task B",
            "--enforcement-tier", "RULE_ENFORCED",
            "--plan-hash", db_doc["plan_sha256"],
            "--json",
        )

        # Pack Task B — must NOT overwrite Task A's per-task pack pointer, and applying Pack A while focused on Task B MUST block!
        r_pb = self._run_harness("web-pack", "--task-id", "disjoint-sibling", "--no-clipboard", "--json")
        self.assertEqual(0, r_pb.returncode, r_pb.stderr)

        merge_a = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": pack_a["pack_id"],
            "task_id": "phased-chat-hop",
            "status": "READY",
            "operations": [
                {
                    "action": "MODIFY",
                    "path": "core/src/main/kotlin/com/demo/core/PriceFormatter.kt",
                    "hunks": [{"search": "    fun formatEgp(piastres: Long): String", "replace": "    fun formatEgp(piastres: Long): String\n    fun prefix(): String = \"EGP\""}],
                },
                {
                    "action": "MODIFY",
                    "path": "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
                    "hunks": [{"search": "        return formatter.formatEgp(total)", "replace": "        return formatter.prefix() + formatter.formatEgp(total)"}],
                },
            ],
        }
        r_wrong_focus = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "apply", "--json",
            stdin_text=json.dumps(merge_a),
        )
        self.assertEqual(1, r_wrong_focus.returncode)
        self.assertIn("ACTIVE_TASK_MISMATCH", r_wrong_focus.stdout)

        # Switch back to Task A (`task switch`) and apply Pack A (`p1` applied, `p2` staged!)
        r_sw = self._run_harness("task", "switch", "--task-id", "phased-chat-hop", "--json")
        self.assertEqual(0, r_sw.returncode, r_sw.stderr)
        r_app_a = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "apply task A", "--json",
            stdin_text=json.dumps(merge_a),
        )
        self.assertEqual(0, r_app_a.returncode, r_app_a.stderr + "\n" + r_app_a.stdout)

        # Save Mid-Task Bridge in Chat 1 (`task bridge --save`) and load it in a BRAND-NEW Chat 2 (`task bridge`)!
        r_bsave = self._run_harness("task", "bridge", "--save", "--task-id", "phased-chat-hop", "--mode", "mid-task", "--json")
        self.assertEqual(0, r_bsave.returncode, r_bsave.stderr)
        bsave_doc = json.loads(r_bsave.stdout)
        self.assertEqual(["p2"], bsave_doc["task_snapshot"]["web_relay"]["staged_phases"])
        self.assertTrue(bsave_doc["task_snapshot"]["web_relay"]["receipt_present"])

        chat2_env = {**self.env, "HARNESS_CONVERSATION_ID": "22222222-3333-4444-5555-666666666666"}
        r_bload = subprocess.run(
            [sys.executable, str(self.repo / ".agents" / "harness.py"), "task", "bridge", "--task-id", "phased-chat-hop", "--json"],
            cwd=str(self.repo), env=chat2_env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, r_bload.returncode, r_bload.stderr + "\n" + r_bload.stdout)
        bload_doc = json.loads(r_bload.stdout)
        self.assertEqual(["p2"], bload_doc["previous_task"]["web_relay"]["staged_phases"])

        # Advance to p2 in Chat 2 and verify router proactively announces `staged_web_phase == "p2"`!
        tdir_a = self.repo / ".agents" / "state" / "tasks" / "phased-chat-hop"
        pdoc_a = read_json(tdir_a / "plan.json")
        pdoc_a["active_phase_index"] = 1
        from plan_authority import save_plan
        save_plan(tdir_a / "plan.json", pdoc_a)

        r_next_c2 = subprocess.run(
            [sys.executable, str(self.repo / ".agents" / "harness.py"), "task", "status", "--task-id", "phased-chat-hop", "--next", "--json"],
            cwd=str(self.repo), env=chat2_env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, r_next_c2.returncode, r_next_c2.stderr)
        next_c2 = json.loads(r_next_c2.stdout)["next_action"]
        self.assertEqual("p2", next_c2.get("staged_web_phase"))

        # Apply staged p2 in Chat 2, then test cross-host continuation (`task continue --host claude --source-stopped`)!
        r_p2_c2 = subprocess.run(
            [sys.executable, str(self.repo / ".agents" / "harness.py"), "web-apply", "--staged-phase", "--source", "conversation", "--proof-reference", "apply staged p2 in chat 2", "--json"],
            cwd=str(self.repo), env=chat2_env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, r_p2_c2.returncode, r_p2_c2.stderr + "\n" + r_p2_c2.stdout)

        r_cont = subprocess.run(
            [sys.executable, str(self.repo / ".agents" / "harness.py"), "task", "continue", "--task-id", "phased-chat-hop", "--host", "claude", "--source-stopped", "--json"],
            cwd=str(self.repo), env=chat2_env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, r_cont.returncode, r_cont.stderr + "\n" + r_cont.stdout)
        self.assertEqual("CONTINUED", json.loads(r_cont.stdout)["status"])

    def test_09_cold_start_room_schema_new_feature_conflict_and_locale(self) -> None:
        """Deep edge cases: bilingual strings.xml auto-pack, @Entity+@Database Room cold-start phases, multi-family NEW_FEATURE, and conflict marker block."""
        # 1. Add Arabic strings.xml + Room @Entity & @Database + multi-family project-facts.json
        ar_dir = self.repo / "app" / "src" / "main" / "res" / "values-ar"
        ar_dir.mkdir(parents=True, exist_ok=True)
        (ar_dir / "strings.xml").write_text(
            '<resources>\n    <string name="app_name">ريلاي ديمو</string>\n</resources>\n',
            encoding="utf-8",
        )
        db_dir = self.repo / "app" / "src" / "main" / "kotlin" / "com" / "demo" / "app" / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        (db_dir / "OrderEntity.kt").write_text(
            "package com.demo.app.db\n\nimport androidx.room.Entity\nimport androidx.room.PrimaryKey\n\n"
            "@Entity(tableName = \"orders\")\ndata class OrderEntity(@PrimaryKey val id: Long, val total: Long)\n",
            encoding="utf-8",
        )
        (db_dir / "AppDatabase.kt").write_text(
            "package com.demo.app.db\n\nimport androidx.room.Database\n\n"
            "@Database(entities = [OrderEntity::class], version = 1)\nabstract class AppDatabase\n",
            encoding="utf-8",
        )
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-qm", "add bilingual strings and Room entity/db")

        # Multi-family hybrid `project-facts.json` (Compose + Fragment) with live `source_fingerprint_sha256` and NO preferred policy
        from project_context import compute_source_fingerprint
        live_fp = compute_source_fingerprint(self.repo)["source_fingerprint_sha256"]
        atomic_write_json(
            self.repo / ".agents" / "project-context" / "project-facts.json",
            {
                "schema_version": 2,
                "source_fingerprint_sha256": live_fp,
                "facts": {
                    "architecture": {
                        "families": [
                            {"id": "compose_mvi", "dimensions": {"ui_toolkit": "compose", "navigation": "navigation_compose"}, "scopes": ["app/src/main/kotlin/com/demo/app/ui"]},
                            {"id": "legacy_fragment", "dimensions": {"ui_toolkit": "xml_views", "navigation": "fragment"}, "scopes": ["app/src/main/kotlin/com/demo/app/legacy"]},
                        ]
                    }
                },
            },
        )

        # 9a. Packing `values/strings.xml` auto-includes `values-ar/strings.xml`, and packing `OrderEntity.kt` auto-includes `AppDatabase.kt`!
        r_pack = self._run_harness(
            "web-pack",
            "--prompt", "Add currency column to OrderEntity and localized label",
            "--file", "app/src/main/res/values/strings.xml",
            "--file", "app/src/main/kotlin/com/demo/app/db/OrderEntity.kt",
            "--no-clipboard",
            "--json",
        )
        self.assertEqual(0, r_pack.returncode, r_pack.stderr)
        pinfo = json.loads(r_pack.stdout)
        self.assertIn("app/src/main/res/values-ar/strings.xml", pinfo["editable_files"])
        self.assertIn("app/src/main/kotlin/com/demo/app/db/AppDatabase.kt", pinfo["editable_files"])

        # 9b. Leftover conflict markers (`<<<<<<<`) in Web output MUST be blocked!
        bad_conflict = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": pinfo["pack_id"],
            "status": "READY",
            "operations": [
                {
                    "action": "MODIFY",
                    "path": "app/src/main/kotlin/com/demo/app/db/OrderEntity.kt",
                    "content": "<<<<<<< HEAD\npackage com.demo.app.db\n=======\npackage other\n>>>>>>> branch\n",
                }
            ],
        }
        r_conf = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "apply conflict", "--json",
            stdin_text=json.dumps(bad_conflict),
        )
        self.assertEqual(1, r_conf.returncode)
        self.assertIn("UNRESOLVED_CONFLICT_MARKERS_BLOCKED", r_conf.stdout)

        # 9c. Cold-start Room Schema (`>=2` impl files) auto-synthesizes `phases` without `PHASE_PLAN_REQUIRED`!
        good_room = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": pinfo["pack_id"],
            "status": "READY",
            "plan_spec": {"task_id": "cold-room-09", "kind": "FEATURE", "outcome": "Add currency column with Migration(1,2)"},
            "operations": [
                {
                    "action": "MODIFY",
                    "path": "app/src/main/kotlin/com/demo/app/db/OrderEntity.kt",
                    "hunks": [{"search": "val total: Long)", "replace": "val total: Long, val currency: String = \"EGP\")"}],
                },
                {
                    "action": "MODIFY",
                    "path": "app/src/main/kotlin/com/demo/app/db/AppDatabase.kt",
                    "hunks": [{"search": "version = 1)", "replace": "version = 2) // Migration(1, 2)"}],
                },
            ],
        }
        r_room = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "apply room migration", "--json",
            stdin_text=json.dumps(good_room),
        )
        self.assertEqual(0, r_room.returncode, r_room.stderr + "\n" + r_room.stdout)
        room_plan = read_json(self.repo / ".agents" / "state" / "tasks" / "cold-room-09" / "plan.json")
        self.assertGreaterEqual(len(room_plan.get("phases") or []), 1)

        # Reset task state to IDLE, refresh hybrid facts fingerprint, and test Cold-Start Pure `CREATE` (`NEW_FEATURE`) on hybrid 2-family repo!
        shutil.rmtree(self.repo / ".agents" / "state" / "tasks" / "cold-room-09", ignore_errors=True)
        (self.repo / ".agents" / "state" / "active-task.json").unlink(missing_ok=True)
        facts_curr = read_json(self.repo / ".agents" / "project-context" / "project-facts.json")
        facts_curr["source_fingerprint_sha256"] = compute_source_fingerprint(self.repo)["source_fingerprint_sha256"]
        atomic_write_json(self.repo / ".agents" / "project-context" / "project-facts.json", facts_curr)

        r_pack_new = self._run_harness(
            "web-pack",
            "--prompt", "Create PromoBannerComposable in Compose",
            "--file", "app/src/main/kotlin/com/demo/app/ui/PromoBannerComposable.kt",
            "--no-clipboard",
            "--json",
        )
        self.assertEqual(0, r_pack_new.returncode, r_pack_new.stderr)
        p_new = json.loads(r_pack_new.stdout)
        create_only_merge = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": p_new["pack_id"],
            "status": "READY",
            "plan_spec": {"task_id": "cold-new-ui-09", "kind": "FEATURE", "outcome": "Create PromoBannerComposable"},
            "operations": [
                {
                    "action": "CREATE",
                    "path": "app/src/main/kotlin/com/demo/app/ui/PromoBannerComposable.kt",
                    "content": "package com.demo.app.ui\n\nannotation class Composable\n\n@Composable\nfun PromoBannerComposable(label: String): String = label\n",
                }
            ],
        }
        r_new_apply = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "apply new compose banner", "--json",
            stdin_text=json.dumps(create_only_merge),
        )
        self.assertEqual(0, r_new_apply.returncode, r_new_apply.stderr + "\n" + r_new_apply.stdout)
        new_plan = read_json(self.repo / ".agents" / "state" / "tasks" / "cold-new-ui-09" / "plan.json")
        self.assertEqual("compose_mvi", (new_plan.get("architecture_contract") or {}).get("target_family_id"))

    def test_10_web_pack_discovery_receipt_and_post_worker_reread_unlock(self) -> None:
        """Hook Chokes #1 & #2: web-pack mints discovery_receipt for grep_search; web-apply expires prior Worker anti-reread choke."""
        # 10a. Run PreToolUse for `web-pack` (registering conversation start), then `web-pack` in `IDLE` -> must mint `latest-discovery.json` so scoped `grep_search` is allowed!
        hook_script = self.repo / ".agents" / "scripts" / "pre_tool_safety.py"
        subprocess.run(
            [sys.executable, str(hook_script)],
            cwd=str(self.repo),
            env=self.env,
            input=json.dumps({
                "conversationId": "conv-disc-check",
                "toolCall": {"name": "run_command", "args": {"CommandLine": "python .agents/harness.py web-pack --file app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt"}},
            }),
            capture_output=True,
            text=True,
            check=False,
        )
        r_pack = self._run_harness(
            "web-pack",
            "--prompt", "Inspect CheckoutCalculator discount clamp",
            "--file", "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
            "--no-clipboard",
            "--json",
        )
        self.assertEqual(0, r_pack.returncode, r_pack.stderr)
        pinfo = json.loads(r_pack.stdout)
        self.assertTrue((self.repo / ".agents" / "cache" / "discovery" / "latest-discovery.json").is_file())

        grep_payload = {
            "conversationId": "conv-disc-check",
            "toolCall": {
                "name": "grep_search",
                "args": {
                    "SearchPath": str(self.repo / "app" / "src" / "main" / "kotlin" / "com" / "demo" / "app"),
                    "Query": "computeTotal",
                },
            },
        }
        p_grep = subprocess.run(
            [sys.executable, str(hook_script)],
            cwd=str(self.repo), env=self.env, input=json.dumps(grep_payload),
            capture_output=True, text=True, check=False,
        )
        v_grep = json.loads(p_grep.stdout)
        self.assertEqual("allow", v_grep["decision"], v_grep)

        # 10b. Apply cold-start task, simulate a completed Worker wave + unresolved `worker-handoff.json`, then switch to `web-apply`!
        merge_1 = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": pinfo["pack_id"],
            "status": "READY",
            "plan_spec": {"task_id": "worker-unlock-10", "kind": "FEATURE", "outcome": "Update CheckoutCalculator"},
            "operations": [
                {
                    "action": "MODIFY",
                    "path": "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
                    "hunks": [{"search": "val clamped = discountPercent.coerceIn(0, 100)", "replace": "val clamped = discountPercent.coerceIn(0, 95)"}],
                }
            ],
        }
        r_app1 = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "apply first", "--json",
            stdin_text=json.dumps(merge_1),
        )
        self.assertEqual(0, r_app1.returncode, r_app1.stderr + "\n" + r_app1.stdout)

        tdir = self.repo / ".agents" / "state" / "tasks" / "worker-unlock-10"
        # Simulate a Worker wave dispatched AFTER `r_app1` that completed with friction (`worker-handoff.json` UNRESOLVED)
        future_ts = "2099-01-01T00:00:00+00:00"
        past_ts = "2020-01-01T00:00:00+00:00"
        atomic_write_json(tdir / "worker-handoff.json", {"status": "UNRESOLVED", "wave_count": 1, "summary": "Worker hit edge case"})
        atomic_write_json(
            self.repo / ".agents" / "state" / "utility-subagents.json",
            {
                "schema_version": 1,
                "entries": [
                    {
                        "wave_id": "wave-worker-test",
                        "parent_conversation_id": "conv-worker-unlock",
                        "agent_type": "harness-worker-agent",
                        "task_id": "worker-unlock-10",
                        "task_status": "IMPLEMENTING",
                        "phase_id": "",
                        "dispatched_at": past_ts,
                        "completed_at": past_ts,
                        "wave_completed": True,
                        "parent_user_turns": 0,
                        "lead_reread_count": 3,
                    }
                ],
            },
        )
        # Re-pack & `web-apply` AFTER the Worker wave -> must mark `worker-handoff.json` `RESOLVED` AND unlock Lead `view_file`!
        r_pack2 = self._run_harness("web-pack", "--task-id", "worker-unlock-10", "--no-clipboard", "--json")
        pinfo2 = json.loads(r_pack2.stdout)
        merge_2 = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": pinfo2["pack_id"],
            "task_id": "worker-unlock-10",
            "status": "READY",
            "operations": [
                {
                    "action": "MODIFY",
                    "path": "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt",
                    "hunks": [{"search": "val clamped = discountPercent.coerceIn(0, 95)", "replace": "val clamped = discountPercent.coerceIn(0, 90)"}],
                }
            ],
        }
        r_app2 = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "apply web takeover", "--json",
            stdin_text=json.dumps(merge_2),
        )
        self.assertEqual(0, r_app2.returncode, r_app2.stderr + "\n" + r_app2.stdout)

        hf_after = read_json(tdir / "worker-handoff.json")
        self.assertEqual("RESOLVED", hf_after["status"])
        self.assertEqual("web_relay", hf_after["resolved_by"])

        view_payload = {
            "conversationId": "conv-worker-unlock",
            "toolCall": {
                "name": "view_file",
                "args": {
                    "AbsolutePath": str(self.repo / "app" / "src" / "main" / "kotlin" / "com" / "demo" / "app" / "CheckoutCalculator.kt"),
                    "StartLine": 1,
                    "EndLine": 30,
                },
            },
        }
        p_view = subprocess.run(
            [sys.executable, str(hook_script)],
            cwd=str(self.repo), env=self.env, input=json.dumps(view_payload),
            capture_output=True, text=True, check=False,
        )
        v_view = json.loads(p_view.stdout)
        self.assertEqual("allow", v_view["decision"], v_view)


    def test_11_thirty_file_refactor_binary_drawables_neighbor_hunks_and_raw_decode(self) -> None:
        """30-file standard daily task + binary .png/.webp/.ttf shield + auto R.drawable/R.font inventory + neighbor hunks + inner ``` fences + trailing comma JSON."""
        # Create binary drawable (.webp), XML vector drawable (.xml), and binary font (.ttf)
        res_draw = self.repo / "app/src/main/res/drawable"
        res_font = self.repo / "app/src/main/res/font"
        res_ar = self.repo / "app/src/main/res/values-ar"
        res_draw.mkdir(parents=True, exist_ok=True)
        res_font.mkdir(parents=True, exist_ok=True)
        res_ar.mkdir(parents=True, exist_ok=True)

        (res_draw / "bg_hero_banner.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 \x00\x01\x02\x03" * 20)
        (res_draw / "ic_calories_ring.xml").write_text(
            '<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="24dp" android:height="24dp" '
            'android:viewportWidth="24" android:viewportHeight="24"><path android:fillColor="#FF5722" android:pathData="M12,2L2,22h20z"/></vector>\n',
            encoding="utf-8",
        )
        (res_font / "cairo_semibold.ttf").write_bytes(b"\x00\x01\x00\x00\x00\x0f\x00\x80TTF_BINARY_DATA" * 15)
        (res_ar / "strings.xml").write_text('<resources>\n    <string name="app_name">ريلاي ديمو</string>\n</resources>\n', encoding="utf-8")

        # Create 30 Kotlin feature files (`FeatureScreen01.kt .. FeatureScreen30.kt`)
        thirty_files: list[str] = []
        for idx in range(1, 31):
            rel = f"app/src/main/kotlin/com/demo/app/FeatureScreen{idx:02d}.kt"
            (self.repo / rel).write_text(
                f"package com.demo.app\n\nimport com.demo.core.PriceFormatter\n\n"
                f"class FeatureScreen{idx:02d}(private val fmt: PriceFormatter) {{\n"
                f"    fun oldPriceLabel(): String = fmt.formatEgp({idx * 100}L)\n"
                f"    fun badgePrice(): String = oldPriceLabel()\n"
                f"}}\n",
                encoding="utf-8",
            )
            thirty_files.append(rel)
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-qm", "add 30 screens + drawables + font")

        # Pack all 30 Kotlin files + strings.xml + binary `bg_hero_banner.webp` + `cairo_semibold.ttf`!
        pack_args = [
            "web-pack",
            "--prompt", "Rename oldPriceLabel -> formattedPriceLabel across all 30 screens, add formatUsd to PriceFormatter, and create ic_streak_flame.xml",
            "--no-clipboard",
            "--files", ",".join(thirty_files + ["app/src/main/res/values/strings.xml", "app/src/main/res/drawable/bg_hero_banner.webp", "app/src/main/res/font/cairo_semibold.ttf"]),
            "--json",
        ]
        r_pack = self._run_harness(*pack_args)
        self.assertEqual(0, r_pack.returncode, r_pack.stderr)
        pinfo = json.loads(r_pack.stdout)

        # 1) All 30 Kotlin files + BOTH EN and AR strings.xml (`32` text files!) packed in ONE single batch (`total_batches == 1`)!
        self.assertEqual(1, pinfo["total_batches"])
        self.assertGreaterEqual(len(pinfo["editable_files"]), 32)
        self.assertIn("app/src/main/res/values-ar/strings.xml", pinfo["editable_files"])

        # 2) Binary `.webp` and `.ttf` were NOT put in `editable_files` or decoded as garbage text; they are in `binary_assets`!
        self.assertNotIn("app/src/main/res/drawable/bg_hero_banner.webp", pinfo["editable_files"])
        self.assertNotIn("app/src/main/res/font/cairo_semibold.ttf", pinfo["editable_files"])
        bin_refs = {b["resource_ref"] for b in pinfo["binary_assets"]}
        self.assertIn("R.drawable.bg_hero_banner", bin_refs)
        self.assertIn("R.font.cairo_semibold", bin_refs)

        bundle_md = Path(pinfo["bundle_file"]).read_text(encoding="utf-8")
        self.assertNotIn("TTF_BINARY_DATA", bundle_md)
        self.assertIn("`R.drawable.bg_hero_banner`", bundle_md)
        self.assertIn("`R.drawable.ic_calories_ring`", bundle_md)
        self.assertIn("`R.font.cairo_semibold`", bundle_md)

        # 3) Build a Gemini Web reply that:
        #    - Modifies all 30 screens using `"replace_all": true`
        #    - Applies a surgical `hunk` to `PriceFormatter.kt` (a `READ_ONLY_NEIGHBOR_SIGNATURE`, NOT in `editable_files`!)
        #    - Creates a brand-new `VectorDrawable` XML `app/src/main/res/drawable/ic_streak_flame.xml`
        #    - Creates a `.md` doc containing inner ```kotlin ... ``` triple backticks!
        #    - Includes an accidental trailing comma before `}` AND trailing conversational `{note}` prose!
        ops = [
            {
                "action": "MODIFY",
                "path": rel,
                "hunks": [{"search": "oldPriceLabel", "replace": "formattedPriceLabel", "replace_all": True}],
            }
            for rel in thirty_files
        ]
        # Surgical hunk on neighbor `PriceFormatter.kt` (not in `editable_files`)!
        ops.append({
            "action": "MODIFY",
            "path": "core/src/main/kotlin/com/demo/core/PriceFormatter.kt",
            "hunks": [{"search": "    fun formatEgp(piastres: Long): String", "replace": "    fun formatEgp(piastres: Long): String\n    fun formatUsd(cents: Long): String"}],
        })
        # Create new VectorDrawable XML!
        ops.append({
            "action": "CREATE",
            "path": "app/src/main/res/drawable/ic_streak_flame.xml",
            "content": '<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="24dp" android:height="24dp" android:viewportWidth="24" android:viewportHeight="24"><path android:fillColor="#FF9800" android:pathData="M12,2C8,7 6,11 6,15a6,6 0 0,0 12,0c0,-4 -2,-8 -6,-13z"/></vector>\n',
        })
        # Create doc containing inner ```kotlin ... ``` fences to prove raw_decode doesn't truncate early!
        ops.append({
            "action": "CREATE",
            "path": "app/src/test/kotlin/com/demo/app/ThirtyScreenRefactorTest.kt",
            "content": 'package com.demo.app\n\nimport org.junit.Test\n\n/**\n * Example:\n * ```kotlin\n * screen.formattedPriceLabel()\n * ```\n */\nclass ThirtyScreenRefactorTest {\n    @Test fun ok() {}\n}\n',
        })

        raw_json_obj = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": pinfo["pack_id"],
            "repo_fingerprint": pinfo["repo_fingerprint"],
            "status": "READY",
            "operations": ops,
        }
        # Inject accidental trailing comma + trailing prose with `{curly braces}`!
        json_str = json.dumps(raw_json_obj, indent=2)
        json_with_quirks = (
            "Here is your complete 30-file refactor!\n\n```json\n"
            + json_str[:-2] + ",\n}"
            + "\n```\n\nNote: verified `{formattedPriceLabel}` across all `{30}` files!"
        )

        r_apply = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "Apply 30-file refactor", "--json",
            stdin_text=json_with_quirks,
        )
        self.assertEqual(0, r_apply.returncode, r_apply.stderr + "\n" + r_apply.stdout)
        app_res = json.loads(r_apply.stdout)
        self.assertEqual("APPLIED", app_res["status"])
        # Because `:core` (`PriceFormatter.kt`) + `:app` (`30` screens + drawable + test) span 2 modules, `p1` writes `:core` and stages all 32 `:app` files in `p2`!
        self.assertIn("core/src/main/kotlin/com/demo/core/PriceFormatter.kt", app_res["files_written"])
        self.assertIn("p2", app_res["staged_future_phases"])
        self.assertGreaterEqual(len(app_res["staged_future_phases"]["p2"]), 32)
        tdir_30 = self.repo / ".agents/state/tasks" / app_res["task_id"]
        pdoc_30 = read_json(tdir_30 / "plan.json")
        pdoc_30["active_phase_index"] = 1
        from plan_authority import save_plan
        save_plan(tdir_30 / "plan.json", pdoc_30)
        r_st_p2 = self._run_harness(
            "web-apply", "--staged-phase", "--source", "conversation", "--proof-reference", "Apply staged p2", "--json"
        )
        self.assertEqual(0, r_st_p2.returncode, r_st_p2.stderr + "\n" + r_st_p2.stdout)
        self.assertGreaterEqual(len(json.loads(r_st_p2.stdout)["files_written"]), 32)
        self.assertIn("formattedPriceLabel", (self.repo / thirty_files[29]).read_text(encoding="utf-8"))
        self.assertNotIn("oldPriceLabel", (self.repo / thirty_files[29]).read_text(encoding="utf-8"))
        self.assertIn("formatUsd", (self.repo / "core/src/main/kotlin/com/demo/core/PriceFormatter.kt").read_text(encoding="utf-8"))
        self.assertTrue((self.repo / "app/src/main/res/drawable/ic_streak_flame.xml").is_file())

    def test_12_hundred_file_dag_batch_sharding_partial_continuation_and_normal_mode_scaling(self) -> None:
        """100-file massive multi-module refactor: auto-sharded 3-batch DAG flow + PARTIAL continuation + Normal Mode Worker/Reviewer adaptive caps."""
        import delegation_policy
        import execution_mode

        hundred_files: list[str] = []
        for idx in range(1, 35):
            rel = f"core/src/main/kotlin/com/demo/core/CoreContract{idx:03d}.kt"
            (self.repo / rel).write_text(
                f"package com.demo.core\n\ninterface CoreContract{idx:03d} {{\n    fun legacyCall(): Int = {idx}\n}}\n",
                encoding="utf-8",
            )
            hundred_files.append(rel)
        for idx in range(35, 101):
            rel = f"app/src/main/kotlin/com/demo/app/AppConsumer{idx:03d}.kt"
            (self.repo / rel).write_text(
                f"package com.demo.app\n\nclass AppConsumer{idx:03d} {{\n    fun legacyCall(): Int = {idx}\n}}\n",
                encoding="utf-8",
            )
            hundred_files.append(rel)
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-qm", "add 100 refactor files")

        execution_mode.set_execution_mode(self.repo, choice="web-project", source="conversation", proof_reference="Web mode for 100-file refactor")

        # 1) Pack all 100 files (default batch_size=40 -> auto-shards into 3 DAG-ordered batches: 40 + 40 + 20!)
        r_b1 = self._run_harness(
            "web-pack",
            "--prompt", "Rename legacyCall -> modernCall across all 100 files",
            "--files", ",".join(hundred_files),
            "--no-clipboard",
            "--json",
        )
        self.assertEqual(0, r_b1.returncode, r_b1.stderr)
        b1_info = json.loads(r_b1.stdout)
        self.assertEqual(1, b1_info["batch_index"])
        self.assertEqual(3, b1_info["total_batches"])
        self.assertEqual(40, len(b1_info["editable_files"]))
        self.assertEqual(60, b1_info["queued_remaining_files"])
        # Verify DAG sort placed `:core` contracts in Batch 1 before `:app` consumers!
        self.assertTrue(b1_info["editable_files"][0].startswith("core/"))

        # 2) Test `PARTIAL` reply on Batch 1: apply first 20 files with `status: "PARTIAL"`, then files 21..40 with `status: "READY"` on SAME `pack_id`!
        b1_files = b1_info["editable_files"]
        part1 = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": b1_info["pack_id"],
            "repo_fingerprint": b1_info["repo_fingerprint"],
            "status": "PARTIAL",
            "operations": [
                {"action": "MODIFY", "path": f, "hunks": [{"search": "legacyCall", "replace": "modernCall", "replace_all": True}]}
                for f in b1_files[:20]
            ],
        }
        r_p1 = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "Apply part 1", "--json",
            stdin_text=json.dumps(part1),
        )
        self.assertEqual(0, r_p1.returncode, r_p1.stderr + "\n" + r_p1.stdout)
        p1_doc = json.loads(r_p1.stdout)
        self.assertEqual("APPLIED_PARTIAL_BATCH", p1_doc["status"])
        self.assertTrue(p1_doc["partial_continuation_open"])
        tid_100 = p1_doc["task_id"]

        # While PARTIAL continuation is open, `delegate-plan` MUST keep task in `WEB_RELAY_ACTIVE`!
        dp_mid = delegation_policy.evaluate_delegation_policy(self.repo, task_id=tid_100)
        self.assertEqual("WEB_RELAY_ACTIVE", dp_mid["strategy"])

        # Complete Batch 1 (`files 21..40`) with `status: "READY"` -> automatically generates Batch 2/3!
        part2 = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": b1_info["pack_id"],
            "repo_fingerprint": b1_info["repo_fingerprint"],
            "status": "READY",
            "operations": [
                {"action": "MODIFY", "path": f, "hunks": [{"search": "legacyCall", "replace": "modernCall", "replace_all": True}]}
                for f in b1_files[20:]
            ],
        }
        r_p2 = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "Apply part 2 of batch 1", "--json",
            stdin_text=json.dumps(part2),
        )
        self.assertEqual(0, r_p2.returncode, r_p2.stderr + "\n" + r_p2.stdout)
        p2_doc = json.loads(r_p2.stdout)
        self.assertEqual("APPLIED_BATCH_NEXT_READY", p2_doc["status"])
        b2_info = p2_doc["next_batch_pack"]
        self.assertIsNotNone(b2_info)
        self.assertEqual(2, b2_info["batch_index"])
        self.assertEqual(3, b2_info["total_batches"])
        self.assertEqual(40, len(b2_info["editable_files"]))

        # `delegate-plan` sees pending Batch 2/3 and stays in `WEB_RELAY_ACTIVE`!
        dp_b2 = delegation_policy.evaluate_delegation_policy(self.repo, task_id=tid_100)
        self.assertEqual("WEB_RELAY_ACTIVE", dp_b2["strategy"])

        # 3) Apply Batch 2/3 (`40` files) -> automatically generates Batch 3/3 (`20` remaining files)!
        b2_reply = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": b2_info["pack_id"],
            "repo_fingerprint": b2_info["repo_fingerprint"],
            "status": "READY",
            "operations": [
                {"action": "MODIFY", "path": f, "hunks": [{"search": "legacyCall", "replace": "modernCall", "replace_all": True}]}
                for f in b2_info["editable_files"]
            ],
        }
        r_app_b2 = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "Apply batch 2", "--json",
            stdin_text=json.dumps(b2_reply),
        )
        self.assertEqual(0, r_app_b2.returncode, r_app_b2.stderr + "\n" + r_app_b2.stdout)
        app_b2_doc = json.loads(r_app_b2.stdout)
        self.assertEqual("APPLIED_BATCH_NEXT_READY", app_b2_doc["status"])
        b3_info = app_b2_doc["next_batch_pack"]
        self.assertEqual(3, b3_info["batch_index"])
        self.assertEqual(20, len(b3_info["editable_files"]))

        # 4) Apply final Batch 3/3 (`20` files) -> status becomes `"APPLIED"` and `delegate-plan` transitions to `WEB_RELAY_APPLIED_VERIFY`!
        b3_reply = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": b3_info["pack_id"],
            "repo_fingerprint": b3_info["repo_fingerprint"],
            "status": "READY",
            "operations": [
                {"action": "MODIFY", "path": f, "hunks": [{"search": "legacyCall", "replace": "modernCall", "replace_all": True}]}
                for f in b3_info["editable_files"]
            ],
        }
        r_app_b3 = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "Apply batch 3", "--json",
            stdin_text=json.dumps(b3_reply),
        )
        self.assertEqual(0, r_app_b3.returncode, r_app_b3.stderr + "\n" + r_app_b3.stdout)
        app_b3_doc = json.loads(r_app_b3.stdout)
        self.assertEqual("APPLIED", app_b3_doc["status"])
        self.assertIsNone(app_b3_doc["next_batch_pack"])

        # Core files (1..34) are live in `p1`, and all 66 `:app` files across Batches 1..3 accumulated in `staged-web-phases/p2.json`!
        self.assertIn("p2", app_b3_doc["staged_future_phases"])
        self.assertEqual(66, len(app_b3_doc["staged_future_phases"]["p2"]))
        tdir_100 = self.repo / ".agents/state/tasks" / tid_100
        pdoc_100 = read_json(tdir_100 / "plan.json")
        pdoc_100["active_phase_index"] = 1
        from plan_authority import save_plan
        save_plan(tdir_100 / "plan.json", pdoc_100)
        r_st_100 = self._run_harness(
            "web-apply", "--staged-phase", "--source", "conversation", "--proof-reference", "Apply accumulated 66 app files in p2", "--json"
        )
        self.assertEqual(0, r_st_100.returncode, r_st_100.stderr + "\n" + r_st_100.stdout)
        self.assertEqual(66, len(json.loads(r_st_100.stdout)["files_written"]))

        # Verify ALL 100 files on disk were cleanly updated!
        for rel in hundred_files:
            body = (self.repo / rel).read_text(encoding="utf-8")
            self.assertIn("modernCall", body, f"{rel} was not updated!")
            self.assertNotIn("legacyCall", body, f"{rel} still has legacyCall!")

        dp_done = delegation_policy.evaluate_delegation_policy(self.repo, task_id=tid_100)
        self.assertEqual("WEB_RELAY_APPLIED_VERIFY", dp_done["strategy"])

        # 5) Verify Normal Mode scale-adaptive Worker & Reviewer budgets on this 100-file active plan (`>32` and `>12`),
        #    plus conflict-marker detection at file #95!
        for step_i in range(45):
            ok_w, rsn_w, _ = delegation_policy.check_and_record_subagent_step_budget(
                self.repo, "worker-100-exec", kind="WORKER", tool_name="view_file", role="harness-worker-agent"
            )
            self.assertTrue(ok_w, f"Worker choked prematurely at read #{step_i + 1} on 100-file task: {rsn_w}")
        for step_r in range(30):
            ok_r, rsn_r, _ = delegation_policy.check_and_record_subagent_step_budget(
                self.repo, "rev-100-exec", kind="REVIEWER", tool_name="view_file", run_id="r100", role="bug-test-reviewer-agent"
            )
            self.assertTrue(ok_r, f"Reviewer choked prematurely at read #{step_r + 1} on 100-file task: {rsn_r}")

        # Conflict marker at file #95 (beyond old `[:32]` cap!) is detected cleanly!
        f95 = self.repo / hundred_files[94]
        orig_95 = f95.read_text(encoding="utf-8")
        f95.write_text("<<<<<<< HEAD\nfun a() = 1\n=======\nfun a() = 2\n>>>>>>> branch\n", encoding="utf-8")
        try:
            has_c, sig_c = execution_mode.has_conflict_signals(self.repo, candidate_files=hundred_files)
            self.assertTrue(has_c)
            self.assertIn(hundred_files[94], sig_c)
        finally:
            f95.write_text(orig_95, encoding="utf-8")


    def test_13_cold_start_90_file_multibatch_need_files_retry_and_review_scale(self) -> None:
        """Cold-start (IDLE) 90-file multi-batch refactor + NEED_FILES batch preservation + --retry failing-file auto-seed + batched review diff/topology."""
        import execution_mode
        import delegation_policy
        from delivery_manifest import build_task_diff, build_task_manifest, load_task_baseline
        from review_package import generate_review_topology
        from _vnext_common import atomic_write_json

        # Ensure clean IDLE repo (no active task) with web-project mode enabled
        self._run_harness("execution-mode", "set", "--choice", "web-project", "--source", "conversation", "--proof-reference", "Use web-project")

        ninety_files: list[str] = []
        for idx in range(1, 31):
            rel = f"core/src/main/java/com/ColdCore{idx}.kt"
            fp = self.repo / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(f"package com\n\nclass ColdCore{idx} {{\n    fun oldApi(): Int = {idx}\n}}\n", encoding="utf-8")
            ninety_files.append(rel)
        for idx in range(1, 61):
            rel = f"app/src/main/java/com/ColdApp{idx}.kt"
            fp = self.repo / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            dep_i = ((idx - 1) % 30) + 1
            fp.write_text(f"package com\n\nclass ColdApp{idx}(private val c: ColdCore{dep_i}) {{\n    fun call(): Int = c.oldApi()\n}}\n", encoding="utf-8")
            ninety_files.append(rel)
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "seed 90 cold-start files"], cwd=self.repo, check=True)

        # 1) Cold-start `web-pack` from IDLE on 90 files -> Batch 1/3 (40), Batch 2/3 (40), Batch 3/3 (10)
        r_b1 = self._run_harness("web-pack", "--files", ",".join(ninety_files), "--prompt", "Rename oldApi to newApi across 90 files", "--json")
        self.assertEqual(0, r_b1.returncode, r_b1.stderr)
        b1 = json.loads(r_b1.stdout)
        self.assertEqual(1, b1["batch_index"])
        self.assertEqual(3, b1["total_batches"])
        self.assertEqual(40, len(b1["editable_files"]))
        self.assertEqual(50, b1["queued_remaining_files"])

        # 2) Gemini Web emits `NEED_FILES` during Batch 1/3 asking for `ColdApp60.kt` (currently sitting in Batch 3/3!)
        nf_reply = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": b1["pack_id"],
            "repo_fingerprint": b1["repo_fingerprint"],
            "status": "NEED_FILES",
            "need_files": ["app/src/main/java/com/ColdApp60.kt"],
            "reason": "Verify final consumer contract",
        }
        r_nf = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "Expand Batch 1", "--json",
            stdin_text=json.dumps(nf_reply),
        )
        self.assertEqual(0, r_nf.returncode, r_nf.stderr + "\n" + r_nf.stdout)
        nf_doc = json.loads(r_nf.stdout)
        self.assertEqual("NEED_FILES_EXPANDED", nf_doc["status"])
        exp_b1 = nf_doc["new_pack"]
        self.assertEqual(1, exp_b1["batch_index"])
        self.assertEqual(3, exp_b1["total_batches"])
        self.assertEqual(41, len(exp_b1["editable_files"]))
        self.assertIn("app/src/main/java/com/ColdApp60.kt", exp_b1["editable_files"])
        # Remaining queued files deduplicated `ColdApp60.kt` (50 -> 49) WITHOUT dropping Batch 2/3 or Batch 3/3!
        self.assertEqual(49, exp_b1["queued_remaining_files"])

        # 3) Apply expanded Batch 1/3 COLD from IDLE -> `plan.json` must register ALL 90 files & multi-module phases `p1`, `p2`!
        b1_ready = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": exp_b1["pack_id"],
            "repo_fingerprint": exp_b1["repo_fingerprint"],
            "status": "READY",
            "plan_spec": {
                "task_id": "cold-90-refactor",
                "kind": "REFACTOR",
                "outcome": "Rename oldApi to newApi across 90 files",
                "approach": "Update :core then :app callers",
                "risks": "Caller parity",
            },
            "operations": [
                {
                    "action": "MODIFY",
                    "path": f,
                    "hunks": [{"search": "oldApi", "replace": "newApi", "replace_all": True}],
                }
                for f in exp_b1["editable_files"]
            ],
        }
        r_app1 = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "Apply cold batch 1", "--json",
            stdin_text=json.dumps(b1_ready),
        )
        self.assertEqual(0, r_app1.returncode, r_app1.stderr + "\n" + r_app1.stdout)
        app1_doc = json.loads(r_app1.stdout)
        self.assertEqual("APPLIED_BATCH_NEXT_READY", app1_doc["status"])
        tid = app1_doc["task_id"]
        plan_90 = read_json(self.repo / ".agents/state/tasks" / tid / "plan.json")
        self.assertEqual(90, len(plan_90["expected_files"]))
        self.assertGreaterEqual(len(plan_90.get("phases") or []), 2)

        # While Batch 2/3 is waiting, delegation_policy stays in WEB_RELAY_ACTIVE and receipt marks incomplete_continuation=True
        rec_after_b1 = read_json(self.repo / ".agents/state/tasks" / tid / "web-relay-receipt.json")
        self.assertTrue(rec_after_b1.get("incomplete_continuation"))
        dp_mid = delegation_policy.evaluate_delegation_policy(self.repo, task_id=tid)
        self.assertEqual("WEB_RELAY_ACTIVE", dp_mid["strategy"])

        # 4) Apply Batch 2/3 and Batch 3/3 -> all 90 files updated!
        b2_info = app1_doc["next_batch_pack"]
        self.assertEqual(2, b2_info["batch_index"])
        r_app2 = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "Apply cold batch 2", "--json",
            stdin_text=json.dumps({
                "schema": "HARNESS_WEB_MERGE_V1",
                "pack_id": b2_info["pack_id"],
                "repo_fingerprint": b2_info["repo_fingerprint"],
                "status": "READY",
                "operations": [
                    {"action": "MODIFY", "path": f, "hunks": [{"search": "oldApi", "replace": "newApi", "replace_all": True}]}
                    for f in b2_info["editable_files"]
                ],
            }),
        )
        self.assertEqual(0, r_app2.returncode, r_app2.stderr)
        b3_info = json.loads(r_app2.stdout)["next_batch_pack"]
        self.assertEqual(3, b3_info["batch_index"])
        self.assertEqual(9, len(b3_info["editable_files"]))
        r_app3 = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "Apply cold batch 3", "--json",
            stdin_text=json.dumps({
                "schema": "HARNESS_WEB_MERGE_V1",
                "pack_id": b3_info["pack_id"],
                "repo_fingerprint": b3_info["repo_fingerprint"],
                "status": "READY",
                "operations": [
                    {"action": "MODIFY", "path": f, "hunks": [{"search": "oldApi", "replace": "newApi", "replace_all": True}]}
                    for f in b3_info["editable_files"]
                ],
            }),
        )
        self.assertEqual(0, r_app3.returncode, r_app3.stderr)
        self.assertEqual("APPLIED", json.loads(r_app3.stdout)["status"])
        rec_final = read_json(self.repo / ".agents/state/tasks" / tid / "web-relay-receipt.json")
        self.assertFalse(rec_final.get("incomplete_continuation"))

        # Apply staged `p2` `:app` files so all 90 files are live on disk
        pdoc_90 = read_json(self.repo / ".agents/state/tasks" / tid / "plan.json")
        pdoc_90["active_phase_index"] = 1
        from plan_authority import save_plan
        save_plan(self.repo / ".agents/state/tasks" / tid / "plan.json", pdoc_90)
        r_st90 = self._run_harness("web-apply", "--staged-phase", "--source", "conversation", "--proof-reference", "Apply p2", "--json")
        self.assertEqual(0, r_st90.returncode, r_st90.stderr)

        # 5) Simulate a failing local gate pointing to `ColdCore1.kt` (from Batch 1/3!) and run `web-pack --retry`:
        #    Verify `ColdCore1.kt` is auto-seeded with its full `FILE:` block even though `latest-web-pack` was Batch 3/3!
        res_dir = self.repo / ".agents/state/results"
        res_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(res_dir / "unit_tests.json", {
            "status": "FAIL",
            "detail": "AssertionError at core/src/main/java/com/ColdCore1.kt:4",
            "output_tail": "Expected 99 in ColdCore1.kt",
        })
        try:
            r_retry = self._run_harness("web-pack", "--task-id", tid, "--retry", "--json")
            self.assertEqual(0, r_retry.returncode, r_retry.stderr)
            ret_doc = json.loads(r_retry.stdout)
            self.assertIn("core/src/main/java/com/ColdCore1.kt", ret_doc["editable_files"])
            ret_md = Path(ret_doc["bundle_file"]).read_text(encoding="utf-8")
            self.assertIn("### FILE: `core/src/main/java/com/ColdCore1.kt`", ret_md)
        finally:
            (res_dir / "unit_tests.json").unlink(missing_ok=True)

        # 6) Verify batched `build_task_diff` and bounded `generate_review_topology` across all 90 modified files!
        tm_90 = build_task_manifest(self.repo, load_task_baseline(self.repo, tid), expected_files=ninety_files)
        diff_90 = build_task_diff(self.repo, tid, tm_90)
        self.assertEqual(90, diff_90.count("diff --git "))
        topo_90 = generate_review_topology(self.repo, ninety_files)
        self.assertIn("additional touched components in this large change-set", topo_90)
        self.assertLess(len(topo_90.encode("utf-8")), 16384)

    def test_14_linux_clipboard_daemon_pipe_safety_reopen_receipt_and_mid_batch_bridge(self) -> None:
        """Linux xclip/wl-copy forked-daemon pipe non-hang + --reopen stale-receipt guard + mid-batch task bridge metadata."""
        import time as _t
        import web_relay
        import delegation_policy
        from unittest import mock

        # 1) Cross-platform (Linux noexec /tmp + macOS + Windows) check for forked clipboard daemon pipe safety:
        fake_dir = Path(self._tmp.name) / "fake_clip_bin"
        fake_dir.mkdir(parents=True, exist_ok=True)
        out_clip_txt = fake_dir / "captured.txt"
        sample_bundle = fake_dir / "sample.md"
        sample_bundle.write_text("# Pack Content\n", encoding="utf-8")
        real_run = subprocess.run

        def _fake_which(cmd_name: str) -> str | None:
            return "/usr/bin/wl-copy" if cmd_name == "wl-copy" else None

        def _proxy_run(cmd_vec: list[str], *a: object, **kw: object) -> subprocess.CompletedProcess:
            self.assertIs(kw.get("stdout"), subprocess.DEVNULL)
            self.assertIs(kw.get("stderr"), subprocess.DEVNULL)
            if os.name != "nt" and Path("/bin/sh").is_file():
                # Spawn a real POSIX child that forks an 8s background daemon inheriting stdout/stderr!
                sh_script = fake_dir / "daemon_clip.sh"
                sh_script.write_text(f"cat > '{out_clip_txt}'\nsleep 8 </dev/null &\nexit 0\n", encoding="utf-8")
                return real_run(["/bin/sh", str(sh_script)], *a, **kw)
            inp = kw.get("input") or b""
            out_clip_txt.write_bytes(inp if isinstance(inp, bytes) else str(inp).encode("utf-8"))
            return subprocess.CompletedProcess(cmd_vec, 0)

        with mock.patch.dict(os.environ, {"HARNESS_NO_CLIPBOARD": "0", "WAYLAND_DISPLAY": "wayland-0"}, clear=False):
            with mock.patch.object(sys, "platform", "linux"), mock.patch("web_relay.shutil.which", side_effect=_fake_which), mock.patch("web_relay.subprocess.run", side_effect=_proxy_run):
                t0 = _t.monotonic()
                clip_res = web_relay._copy_to_clipboard(sample_bundle, "Hello Wayland & X11!")
                elapsed = _t.monotonic() - t0
        self.assertTrue(clip_res["copied"])
        self.assertEqual("linux_wl_copy", clip_res["mode"])
        self.assertLess(elapsed, 1.5, f"Forked clipboard daemon hung parent pipes ({elapsed:.2f}s)!")
        self.assertEqual("Hello Wayland & X11!", out_clip_txt.read_text(encoding="utf-8"))

        # 2) Verify `--reopen` on a READY_FOR_DELIVERY web-mode task invalidates stale `WEB_RELAY_APPLIED_VERIFY`
        #    until the reopened change is actually packed/applied!
        self._run_harness("execution-mode", "set", "--choice", "web-project", "--source", "conversation", "--proof-reference", "Use web-project")
        reopen_f = "app/src/main/java/com/ReopenScreen.kt"
        (self.repo / reopen_f).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / reopen_f).write_text('package com\nclass ReopenScreen { fun label() = "v1" }\n', encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "seed ReopenScreen"], cwd=self.repo, check=True)

        p_re = json.loads(self._run_harness("web-pack", "--file", reopen_f, "--prompt", "Update ReopenScreen to v2", "--json").stdout)
        r_ap = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "Apply v2", "--json",
            stdin_text=json.dumps({
                "schema": "HARNESS_WEB_MERGE_V1",
                "pack_id": p_re["pack_id"],
                "repo_fingerprint": p_re["repo_fingerprint"],
                "status": "READY",
                "plan_spec": {"task_id": "reopen-web-chk", "kind": "FEATURE", "outcome": "Update ReopenScreen", "approach": "Update label", "risks": "None"},
                "operations": [{"action": "MODIFY", "path": reopen_f, "hunks": [{"search": '"v1"', "replace": '"v2"'}]}],
            }),
        )
        self.assertEqual(0, r_ap.returncode, r_ap.stderr)
        dp_before_reopen = delegation_policy.evaluate_delegation_policy(self.repo, task_id="reopen-web-chk")
        self.assertEqual("WEB_RELAY_APPLIED_VERIFY", dp_before_reopen["strategy"])

        # Transition plan to READY_FOR_DELIVERY, sleep 20ms so resumed_at > applied_at, then run `task resume --reopen`
        from plan_authority import save_plan
        from delivery_manifest import build_manifest
        p_path = self.repo / ".agents/state/tasks/reopen-web-chk/plan.json"
        p_doc = read_json(p_path)
        p_doc["status"] = "READY_FOR_DELIVERY"
        p_doc["ready_delivery_snapshot_sha256"] = build_manifest(self.repo)["delivery_snapshot_sha256"]
        save_plan(p_path, p_doc)
        _t.sleep(0.02)
        r_res = self._run_harness("task", "resume", "--task-id", "reopen-web-chk", "--reopen", "--json")
        self.assertEqual(0, r_res.returncode, r_res.stderr + "\n" + r_res.stdout)

        # Immediately after `--reopen` (before v3 is applied), strategy MUST be WEB_RELAY_ACTIVE (not stale WEB_RELAY_APPLIED_VERIFY!)
        dp_after_reopen = delegation_policy.evaluate_delegation_policy(self.repo, task_id="reopen-web-chk")
        self.assertEqual("WEB_RELAY_ACTIVE", dp_after_reopen["strategy"])

        # 3) Verify mid-batch `task bridge --save` records `batch_index` and `total_batches` cleanly!
        batch_files = []
        for idx in range(1, 46):
            bf = f"app/src/main/java/com/BridgeBatch{idx}.kt"
            (self.repo / bf).write_text(f"package com\nclass BridgeBatch{idx} {{ fun v() = {idx} }}\n", encoding="utf-8")
            batch_files.append(bf)
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "seed 45 bridge batch files"], cwd=self.repo, check=True)
        self._run_harness("task", "cancel", "--task-id", "reopen-web-chk", "--source", "conversation", "--proof-reference", "cancel test task")

        b1_br = json.loads(self._run_harness("web-pack", "--files", ",".join(batch_files), "--prompt", "Update 45 files", "--json").stdout)
        r_br_ap1 = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "Apply batch 1 of 2", "--json",
            stdin_text=json.dumps({
                "schema": "HARNESS_WEB_MERGE_V1",
                "pack_id": b1_br["pack_id"],
                "repo_fingerprint": b1_br["repo_fingerprint"],
                "status": "READY",
                "plan_spec": {"task_id": "bridge-batch-45", "kind": "REFACTOR", "outcome": "Update 45 files", "approach": "2 batches", "risks": "None"},
                "operations": [{"action": "MODIFY", "path": f, "hunks": [{"search": "fun v()", "replace": "fun vUpdated()"}]} for f in b1_br["editable_files"]],
            }),
        )
        self.assertEqual(0, r_br_ap1.returncode, r_br_ap1.stderr)
        r_bsave = self._run_harness("task", "bridge", "--save", "--task-id", "bridge-batch-45", "--json")
        self.assertEqual(0, r_bsave.returncode, r_bsave.stderr)
        bsave_doc = json.loads(r_bsave.stdout)
        wr_snap = (bsave_doc.get("task_snapshot") or {}).get("web_relay") or {}
        self.assertEqual(2, wr_snap.get("batch_index"))
        self.assertEqual(2, wr_snap.get("total_batches"))
        self.assertTrue(wr_snap.get("unapplied_pack_id"))

    def test_15_git_dirty_working_tree_capture_and_web_apply_dry_run_preview(self) -> None:
        """Studio-to-Web Git dirty capture (`--dirty` & IDLE auto-dirty) + read-only `web-apply --dry-run` preview & lint warning."""
        self._run_harness("execution-mode", "set", "--choice", "auto-project", "--source", "conversation", "--proof-reference", "Use smart auto")

        # 1) Create 2 modified tracked Kotlin files + 1 untracked new Kotlin screen + 1 secret file + 1 build artifact
        mod_a = "app/src/main/kotlin/com/demo/app/CheckoutCalculator.kt"
        new_b = "app/src/main/kotlin/com/demo/app/DirtyPromoBanner.kt"
        (self.repo / mod_a).write_text(
            (self.repo / mod_a).read_text(encoding="utf-8") + "\n// WIP local edit in Android Studio\n",
            encoding="utf-8",
        )
        (self.repo / new_b).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / new_b).write_text("package com.demo.app\n\nclass DirtyPromoBanner {\n    fun text() = \"VIP\"\n}\n", encoding="utf-8")
        (self.repo / "local.properties").write_text("sdk.dir=/secret/sdk\napi_key=\"sk-1234567890123456789012345\"\n", encoding="utf-8")
        (self.repo / "app/build/generated/BuildNoise.kt").parent.mkdir(parents=True, exist_ok=True)
        (self.repo / "app/build/generated/BuildNoise.kt").write_text("package gen\nclass BuildNoise\n", encoding="utf-8")

        # 1a) IDLE auto-dirty fallback: prompt mentions no symbol names ("Finish open edits") -> captures dirty source files automatically!
        r_auto_dirty = self._run_harness("web-pack", "--prompt", "Finish open working tree changes cleanly", "--json")
        self.assertEqual(0, r_auto_dirty.returncode, r_auto_dirty.stderr)
        ad_doc = json.loads(r_auto_dirty.stdout)
        self.assertIn(mod_a, ad_doc["editable_files"])
        self.assertIn(new_b, ad_doc["editable_files"])
        self.assertIn(mod_a, ad_doc["git_dirty_files_included"])
        self.assertIn(new_b, ad_doc["git_dirty_files_included"])
        self.assertNotIn("local.properties", ad_doc["editable_files"])
        self.assertNotIn("app/build/generated/BuildNoise.kt", ad_doc["editable_files"])

        # 1b) Explicit `--dirty` alongside `--file` combines explicit file + all dirty working-tree files!
        r_exp_dirty = self._run_harness(
            "web-pack", "--file", "core/src/main/kotlin/com/demo/core/PriceFormatter.kt", "--dirty", "--prompt", "Wire CartRepository with open edits", "--json"
        )
        self.assertEqual(0, r_exp_dirty.returncode, r_exp_dirty.stderr)
        ed_doc = json.loads(r_exp_dirty.stdout)
        self.assertIn("core/src/main/kotlin/com/demo/core/PriceFormatter.kt", ed_doc["editable_files"])
        self.assertIn(mod_a, ed_doc["editable_files"])
        self.assertIn(new_b, ed_doc["editable_files"])

        # 2) Verify `PreToolUse` allows `web-apply --dry-run` WITHOUT `--source` / `--proof-reference` (read-only!)
        hook_proc = subprocess.run(
            [sys.executable, str(self.repo / ".agents/scripts/pre_tool_safety.py")],
            cwd=self.repo,
            input=json.dumps({
                "conversationId": "conv-dry-run",
                "toolCall": {"name": "run_command", "args": {"CommandLine": "python .agents/harness.py web-apply --dry-run --json"}},
            }),
            text=True,
            capture_output=True,
            check=False,
        )
        hook_res = json.loads(hook_proc.stdout)
        self.assertEqual("allow", (hook_res.get("hookSpecificOutput") or {}).get("permissionDecision") or hook_res.get("decision"))

        # 3) Run `web-apply --dry-run` -> verifies diff stats + static wildcard warning + ZERO disk writes + pack remains unconsumed!
        before_banner = (self.repo / new_b).read_text(encoding="utf-8")
        merge_reply = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": ed_doc["pack_id"],
            "repo_fingerprint": ed_doc["repo_fingerprint"],
            "status": "READY",
            "plan_spec": {
                "task_id": "dirty-dryrun-feat",
                "kind": "FEATURE",
                "outcome": "Wire CartRepository with DirtyPromoBanner",
                "approach": "Update banner & create test",
                "risks": "None",
            },
            "operations": [
                {
                    "action": "MODIFY",
                    "path": new_b,
                    "hunks": [{"search": "package com.demo.app", "replace": "package com.demo.app\nimport java.util.*"}],
                },
                {
                    "action": "CREATE",
                    "path": "app/src/test/kotlin/com/demo/app/DirtyPromoBannerTest.kt",
                    "content": "package com.demo.app\nimport org.junit.Test\nclass DirtyPromoBannerTest {\n    @Test fun ok() {}\n}\n",
                },
            ],
        }
        r_dry = self._run_harness("web-apply", "--dry-run", "--stdin", "--json", stdin_text=json.dumps(merge_reply))
        self.assertEqual(0, r_dry.returncode, r_dry.stderr + "\n" + r_dry.stdout)
        dry_doc = json.loads(r_dry.stdout)
        self.assertEqual("DRY_RUN_OK", dry_doc["status"])
        self.assertTrue(dry_doc["dry_run"])
        self.assertFalse(dry_doc["disk_modified"])
        self.assertFalse(dry_doc["pack_consumed"])
        self.assertEqual(2, dry_doc["summary"]["files_to_write"])
        self.assertGreaterEqual(dry_doc["summary"]["total_added_lines"], 5)
        self.assertTrue(any("wildcard import" in w for w in dry_doc["static_preview_warnings"]))
        # Verify disk was NOT touched and test file was NOT created during dry-run!
        self.assertEqual(before_banner, (self.repo / new_b).read_text(encoding="utf-8"))
        self.assertFalse((self.repo / "app/src/test/kotlin/com/demo/app/DirtyPromoBannerTest.kt").exists())

        # 3b) Also verify `--dry-run` catches lazy truncation BEFORE touching disk!
        bad_reply = dict(merge_reply, operations=[{"action": "CREATE", "path": "app/src/main/java/com/Bad.kt", "content": "package com\n// ... rest of code unchanged\n"}])
        r_bad_dry = self._run_harness("web-apply", "--dry-run", "--stdin", "--json", stdin_text=json.dumps(bad_reply))
        self.assertNotEqual(0, r_bad_dry.returncode)
        self.assertIn("LAZY_TRUNCATION_BLOCKED", r_bad_dry.stdout + r_bad_dry.stderr)

        # 4) Now apply the clean version for real on the SAME `pack_id` -> succeeds 100% because `--dry-run` did not consume `pack_id`!
        clean_reply = dict(
            merge_reply,
            operations=[
                {
                    "action": "MODIFY",
                    "path": new_b,
                    "hunks": [{"search": 'fun text() = "VIP"', "replace": 'fun text() = "VIP_GOLD"'}],
                },
                merge_reply["operations"][1],
            ],
        )
        r_real = self._run_harness(
            "web-apply", "--stdin", "--source", "conversation", "--proof-reference", "Looks good after dry-run, apply!", "--json",
            stdin_text=json.dumps(clean_reply),
        )
        self.assertEqual(0, r_real.returncode, r_real.stderr + "\n" + r_real.stdout)
        self.assertEqual("APPLIED", json.loads(r_real.stdout)["status"])
        self.assertIn("VIP_GOLD", (self.repo / new_b).read_text(encoding="utf-8"))
        self.assertTrue((self.repo / "app/src/test/kotlin/com/demo/app/DirtyPromoBannerTest.kt").is_file())

if __name__ == "__main__":
    unittest.main()
