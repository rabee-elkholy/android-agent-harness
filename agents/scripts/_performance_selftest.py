"""Reference benchmark for snapshot and policy overhead (Gradle/ADB/AI excluded)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from delivery_manifest import build_manifest  # noqa: E402
from review_policy import decide  # noqa: E402


def git(repo: Path, *args: str) -> None:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, check=False)
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode(errors="replace"))


def main() -> int:
    count = int(os.environ.get("HARNESS_BENCH_FILES", "20000"))
    with tempfile.TemporaryDirectory() as temp:
        repo = Path(temp)
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Harness Benchmark")
        git(repo, "config", "user.email", "benchmark@example.invalid")
        source = repo / "app/src/main/kotlin/bench"
        source.mkdir(parents=True)
        for index in range(count):
            (source / f"F{index:06d}.kt").write_text(f"internal const val F{index:06d} = {index}\n", encoding="utf-8")
        (repo / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "fixture")
        changed = source / "F000000.kt"
        changed.write_text("internal const val F000000 = -1\n", encoding="utf-8")
        started = time.perf_counter()
        manifest = build_manifest(repo)
        manifest_seconds = time.perf_counter() - started
        classification = {
            "classification_sha256": "c" * 64, "surfaces": ["BUSINESS_LOGIC"],
            "severity": "MEDIUM", "confidence": "HIGH", "changed_files": 1,
        }
        started = time.perf_counter()
        for _ in range(100):
            decide(classification, SCRIPTS.parent / "skills")
        policy_ms = (time.perf_counter() - started) * 10
        print(f"manifest_files={len(manifest['files'])} manifest_seconds={manifest_seconds:.3f}")
        print(f"policy_average_ms={policy_ms:.3f}")
        # CI runners and Windows antivirus vary substantially. This is a
        # regression tripwire; published sub-second values are measured on the
        # documented reference machine, not promised to every client.
        if len(manifest["files"]) != count + 1 or manifest_seconds > 5.0 or policy_ms > 150.0:
            print("[FAIL] vNext overhead exceeded the CI regression budget", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
