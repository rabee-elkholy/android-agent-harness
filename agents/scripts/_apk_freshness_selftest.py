"""Self-test suite for _apk_freshness.py.

Validates detection of missing, fresh, and stale APKs across various
repository states, timestamp deltas, and file modification categories.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _apk_freshness import check_apk_freshness, format_freshness_error  # noqa: E402


def test_missing_apk() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        non_existent_apk = repo / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
        verdict = check_apk_freshness(non_existent_apk, repo)
        assert not verdict.is_fresh, "Expected missing APK to not be fresh"
        assert verdict.status == "MISSING_APK", f"Expected MISSING_APK, got {verdict.status}"
        assert "APK not found" in verdict.reason


def test_fresh_apk() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        apk_dir = repo / "app" / "build" / "outputs" / "apk" / "debug"
        apk_dir.mkdir(parents=True, exist_ok=True)
        apk_file = apk_dir / "app-debug.apk"
        apk_file.write_bytes(b"dummy apk content")

        # Set APK mtime to current time + 10s to simulate freshly built APK
        now = time.time()
        os.utime(apk_file, (now + 10, now + 10))

        verdict = check_apk_freshness(apk_file, repo)
        assert verdict.is_fresh, f"Expected fresh APK, got: {verdict.reason}"
        assert verdict.status == "FRESH"


def test_stale_source_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        apk_dir = repo / "app" / "build" / "outputs" / "apk" / "debug"
        apk_dir.mkdir(parents=True, exist_ok=True)
        apk_file = apk_dir / "app-debug.apk"
        apk_file.write_bytes(b"old apk content")

        src_dir = repo / "app" / "src" / "main" / "java" / "com" / "example"
        src_dir.mkdir(parents=True, exist_ok=True)
        kt_file = src_dir / "NewFeatureActivity.kt"
        kt_file.write_text("class NewFeatureActivity", encoding="utf-8")

        base_time = time.time()
        # APK was built at base_time - 100
        os.utime(apk_file, (base_time - 100, base_time - 100))
        # kt_file was modified at base_time (100 seconds newer)
        os.utime(kt_file, (base_time, base_time))

        # Mock changed_paths in _apk_freshness
        import _apk_freshness
        orig_changed_paths = _apk_freshness.changed_paths
        _apk_freshness.changed_paths = lambda: [kt_file]
        try:
            verdict = check_apk_freshness(apk_file, repo)
            assert not verdict.is_fresh, "Expected stale APK detection"
            assert verdict.status == "STALE_SOURCE", f"Expected STALE_SOURCE, got {verdict.status}"
            assert verdict.stale_file is not None
            assert "NewFeatureActivity.kt" in verdict.stale_file
            assert verdict.time_diff_sec is not None and verdict.time_diff_sec >= 90
            err_banner = format_freshness_error(verdict, apk_file)
            assert "STALE APK DETECTED" in err_banner
            assert "NewFeatureActivity.kt" in err_banner
        finally:
            _apk_freshness.changed_paths = orig_changed_paths


def test_stale_manifest_and_resources() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        apk_file = repo / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
        apk_file.parent.mkdir(parents=True, exist_ok=True)
        apk_file.write_bytes(b"apk content")

        manifest = repo / "app" / "src" / "main" / "AndroidManifest.xml"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("<manifest/>", encoding="utf-8")

        base_time = time.time()
        os.utime(apk_file, (base_time - 50, base_time - 50))
        os.utime(manifest, (base_time, base_time))

        import _apk_freshness
        orig_changed_paths = _apk_freshness.changed_paths
        _apk_freshness.changed_paths = lambda: [manifest]
        try:
            verdict = check_apk_freshness(apk_file, repo)
            assert not verdict.is_fresh
            assert verdict.status == "STALE_SOURCE"
            assert "AndroidManifest.xml" in (verdict.stale_file or "")
        finally:
            _apk_freshness.changed_paths = orig_changed_paths


def test_docs_and_harness_state_ignored() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        apk_file = repo / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
        apk_file.parent.mkdir(parents=True, exist_ok=True)
        apk_file.write_bytes(b"apk content")

        doc_file = repo / "docs" / "guide.md"
        doc_file.parent.mkdir(parents=True, exist_ok=True)
        doc_file.write_text("# Guide", encoding="utf-8")

        state_file = repo / ".agents" / "state" / "cache.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("{}", encoding="utf-8")

        base_time = time.time()
        os.utime(apk_file, (base_time - 50, base_time - 50))
        os.utime(doc_file, (base_time, base_time))
        os.utime(state_file, (base_time, base_time))

        import _apk_freshness
        orig_changed_paths = _apk_freshness.changed_paths
        _apk_freshness.changed_paths = lambda: [doc_file, state_file]
        try:
            verdict = check_apk_freshness(apk_file, repo)
            assert verdict.is_fresh, f"Expected non-app files to be ignored, got: {verdict.reason}"
            assert verdict.status == "FRESH"
        finally:
            _apk_freshness.changed_paths = orig_changed_paths


def test_failed_assemble_gate_detection() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        apk_file = repo / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
        apk_file.parent.mkdir(parents=True, exist_ok=True)
        apk_file.write_bytes(b"apk content")

        results_dir = repo / ".agents" / "state" / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        gate_file = results_dir / "gradle-app-assembledebug.json"
        gate_file.write_text(json.dumps({
            "status": "FAIL",
            "exit_code": 1,
            "git_sha": "abcdef1234567890abcdef1234567890abcdef12",
        }), encoding="utf-8")

        import _apk_freshness
        orig_changed_paths = _apk_freshness.changed_paths
        orig_read_gate = _apk_freshness.read_gate_result
        _apk_freshness.changed_paths = lambda: []
        _apk_freshness.read_gate_result = lambda name: json.loads(gate_file.read_text(encoding="utf-8")) if "assembledebug" in name else None
        try:
            verdict = check_apk_freshness(apk_file, repo)
            assert not verdict.is_fresh
            assert verdict.status == "FAILED_BUILD"
        finally:
            _apk_freshness.changed_paths = orig_changed_paths
            _apk_freshness.read_gate_result = orig_read_gate


def main() -> int:
    print("[*] Running _apk_freshness_selftest.py...")
    test_missing_apk()
    print("    - test_missing_apk: [PASS]")
    test_fresh_apk()
    print("    - test_fresh_apk: [PASS]")
    test_stale_source_file()
    print("    - test_stale_source_file: [PASS]")
    test_stale_manifest_and_resources()
    print("    - test_stale_manifest_and_resources: [PASS]")
    test_docs_and_harness_state_ignored()
    print("    - test_docs_and_harness_state_ignored: [PASS]")
    test_failed_assemble_gate_detection()
    print("    - test_failed_assemble_gate_detection: [PASS]")
    print("[SUCCESS] All _apk_freshness_selftest assertions passed cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
