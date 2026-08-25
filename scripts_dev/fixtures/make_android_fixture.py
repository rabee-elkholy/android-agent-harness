"""Deterministic Android project fixture builder for harness selftests.

Promotes the ad-hoc temp-project builders previously inlined in
_hook_selftest.py into one reusable, stdlib-only generator. Each profile lays
down a minimal but realistic checkout and prints its root path to stdout.

Usage:
    python scripts_dev/fixtures/make_android_fixture.py --profile classic
    python scripts_dev/fixtures/make_android_fixture.py --profile multimodule
    python scripts_dev/fixtures/make_android_fixture.py --profile flavors
    python scripts_dev/fixtures/make_android_fixture.py --profile kmp

Programmatic use:
    from make_android_fixture import make_fixture
    root = make_fixture("flavors")
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

FLAVORS_GRADLE = (
    'android {\n'
    '    flavorDimensions += "env"\n'
    '    productFlavors {\n'
    '        create("staging") { dimension = "env" }\n'
    '        create("prodClient") { dimension = "env" }\n'
    '        isDefault = true\n'
    '    }\n'
    '}\n'
)

KMP_SETTINGS = (
    'pluginManagement { repositories { gradlePluginPortal() } }\n'
    'rootProject.name = "kmp-fixture"\n'
    'include(":shared")\n'
)

KMP_SHARED_GRADLE = (
    'kotlin {\n'
    '    androidTarget()\n'
    '    sourceSets {\n'
    '        val commonMain by getting\n'
    '        val androidMain by getting\n'
    '    }\n'
    '}\n'
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def make_fixture(profile: str, root: Path | None = None) -> Path:
    root = root or Path(tempfile.mkdtemp(prefix="ahk-fixture-"))
    root.mkdir(parents=True, exist_ok=True)
    _write(root / "gradlew.bat", "rem gradle wrapper fixture\n")

    if profile == "classic":
        _write(
            root / "app" / "build.gradle.kts",
            'plugins { id("com.android.application") }\nandroid {}\n',
        )
        _write(root / "app" / "src" / "main" / "AndroidManifest.xml", '<manifest package="com.fixture.app"/>\n')
        _write(root / "app" / "src" / "main" / "java" / "A.kt", "class A\n")
        return root

    if profile == "multimodule":
        _write(root / "app" / "build.gradle.kts", 'plugins { id("com.android.application") }\n')
        _write(root / "core" / "data" / "build.gradle.kts", 'plugins { id("com.android.library") }\n')
        _write(root / "app" / "src" / "main" / "java" / "A.kt", "class A\n")
        _write(root / "core" / "data" / "src" / "main" / "kotlin" / "B.kt", "class B\n")
        return root

    if profile == "flavors":
        _write(root / "app" / "build.gradle.kts", FLAVORS_GRADLE)
        _write(root / "app" / "src" / "main" / "AndroidManifest.xml", '<manifest package="com.fixture.flavors"/>\n')
        _write(root / "app" / "src" / "main" / "java" / "A.kt", "class A\n")
        return root

    if profile == "kmp":
        _write(root / "settings.gradle.kts", KMP_SETTINGS)
        _write(root / "shared" / "build.gradle.kts", KMP_SHARED_GRADLE)
        _write(root / "shared" / "src" / "commonMain" / "kotlin" / "Shared.kt", "expect fun platform(): String\n")
        _write(root / "shared" / "src" / "androidMain" / "kotlin" / "Shared.android.kt", "actual fun platform() = \"android\"\n")
        return root

    raise SystemExit(f"Unknown fixture profile: {profile}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a deterministic Android project fixture.")
    parser.add_argument(
        "--profile",
        required=True,
        choices=("classic", "multimodule", "flavors", "kmp"),
        help="Fixture shape to generate.",
    )
    parser.add_argument("--root", default=None, help="Optional explicit directory (default: fresh temp dir).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = make_fixture(args.profile, Path(args.root).resolve() if args.root else None)
    print(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
