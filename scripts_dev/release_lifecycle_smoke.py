"""Exercise the built wheel through a clean client lifecycle.

This acceptance smoke test is intentionally host-neutral and does not require an
Android SDK.  It verifies that the artifact users install contains a functional
engine and that install/update/uninstall/reinstall remain ownership-safe.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        rendered = " ".join(command)
        raise RuntimeError(
            f"command failed ({result.returncode}): {rendered}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def write_fixture(repo: Path) -> dict[str, str]:
    files = {
        "gradlew.bat": "@echo off\r\nrem deterministic wrapper placeholder\r\n",
        "settings.gradle.kts": 'rootProject.name = "release-smoke"\ninclude(":app")\n',
        "app/build.gradle.kts": 'plugins { id("com.android.application") }\nandroid { namespace = "com.example.smoke" }\n',
        "app/src/main/AndroidManifest.xml": '<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.example.smoke"><application><activity android:name=".MainActivity" android:exported="true" /></application></manifest>\n',
        "app/src/main/java/com/example/smoke/MainActivity.kt": "package com.example.smoke\nclass MainActivity\n",
        "AGENTS.md": "# Project-owned instructions\n",
    }
    for relative, content in files.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
    answers = {
        "product": "Release Smoke",
        "application_id": "com.example.smoke",
        "launcher": "com.example.smoke/.MainActivity",
        "application_module": ":app",
        "assemble": ":app:assembleDebug",
        "unit_test_task": ":app:testDebugUnitTest",
        "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
        "build_variant": "Debug",
        "tools": ["codex"],
        "pm_provider": "zoho_sprints",
        "zoho_mcp": "disable",
        "backup": True,
    }
    answer_path = repo / ".harness-setup/answers.json"
    answer_path.parent.mkdir(parents=True, exist_ok=True)
    answer_path.write_text(json.dumps(answers, indent=2) + "\n", encoding="utf-8")
    return {
        relative: sha256(repo / relative)
        for relative in files
        if relative != "AGENTS.md"
    }


def assert_project_unchanged(repo: Path, expected: dict[str, str]) -> None:
    changed = [relative for relative, digest in expected.items() if sha256(repo / relative) != digest]
    if changed:
        raise RuntimeError("harness lifecycle changed project-owned files: " + ", ".join(changed))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--wheel", help="Built android-agent-harness wheel")
    source.add_argument("--wheel-dir", help="Directory containing exactly one built wheel")
    args = parser.parse_args(argv)
    if args.wheel_dir:
        wheels = sorted(Path(args.wheel_dir).resolve().glob("android_agent_harness-*.whl"))
        if len(wheels) != 1:
            parser.error(f"expected exactly one android-agent-harness wheel, found {len(wheels)}")
        wheel = wheels[0]
    else:
        wheel = Path(args.wheel).resolve()
    if not wheel.is_file():
        parser.error(f"wheel does not exist: {wheel}")

    with tempfile.TemporaryDirectory(prefix="android-harness-release-") as raw:
        root = Path(raw)
        environment = root / "venv"
        repo = root / "android-project"
        repo.mkdir()
        expected = write_fixture(repo)
        run(["git", "init", "--quiet"], cwd=repo)
        run(["git", "config", "user.name", "Harness Release Smoke"], cwd=repo)
        run(["git", "config", "user.email", "release-smoke@example.invalid"], cwd=repo)
        run(["git", "add", "."], cwd=repo)
        run(["git", "commit", "--quiet", "-m", "Create Android release fixture"], cwd=repo)

        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = venv_python(environment)
        run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", str(wheel)])
        probe = run(
            [
                str(python),
                "-c",
                "from pathlib import Path; import harness_cli; print(Path(harness_cli.__file__).resolve().parent)",
            ],
            cwd=root,
        )
        kit = Path(probe.stdout.strip())
        lifecycle = kit / "agents/scripts/lifecycle.py"
        cli = kit / "harness_cli.py"
        if not lifecycle.is_file() or not cli.is_file():
            raise RuntimeError(f"installed wheel is missing runtime files under {kit}")

        base = [str(python), str(lifecycle)]
        run([*base, "--json", "install", "--repo", str(repo), "--kit", str(kit)])
        run([str(python), str(cli), "doctor", "--repo", str(repo), "--kit", str(kit), "--json"])
        run([*base, "--json", "update", "--repo", str(repo), "--kit", str(kit)])
        preview = run([*base, "--json", "uninstall", "--repo", str(repo)])
        if json.loads(preview.stdout).get("status") != "DRY_RUN":
            raise RuntimeError("uninstall preview did not remain non-mutating")
        run([*base, "--json", "uninstall", "--repo", str(repo), "--apply"])
        if (repo / ".agents").exists():
            raise RuntimeError("uninstall left the managed engine in place")
        assert_project_unchanged(repo, expected)
        if (repo / "AGENTS.md").read_text(encoding="utf-8") != "# Project-owned instructions\n":
            raise RuntimeError("uninstall did not restore the project-owned AGENTS.md")
        run([*base, "--json", "install", "--repo", str(repo), "--kit", str(kit)])
        assert_project_unchanged(repo, expected)

    print(f"[PASS] wheel lifecycle smoke: {wheel.name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
