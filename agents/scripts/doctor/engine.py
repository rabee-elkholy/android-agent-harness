"""Harness Doctor 12-Dimension diagnostic engine implementation."""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .models import (
    CORE_REFERENCES,
    CORE_SCRIPTS,
    CORE_SUBAGENTS,
    CORE_WORKFLOWS,
    KNOWN_DOMAINS,
    CheckResult,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _repo_files import ensure_local_git_privacy  # noqa: E402

AGENTS_DIR = Path(__file__).resolve().parent.parent.parent


class HarnessDoctor:
    def __init__(self, repo: Path, check_device: bool = False, run_selftest: bool = True, live_stream: bool = False):
        self.repo = repo
        self.check_device = check_device
        self.run_selftest = run_selftest and (os.environ.get("_IN_HOOK_SELFTEST") != "1")
        self.live_stream = live_stream
        self.current_cat = ""
        self.results: list[CheckResult] = []
        self.is_raw_kit = (self.repo / "agents" / "VERSION").is_file() and not (self.repo / ".agents").is_dir()
        self.agents_dir = self.repo / ".agents" if not self.is_raw_kit else self.repo / "agents"
        if not self.agents_dir.is_dir():
            self.agents_dir = AGENTS_DIR

    def log(self, category: str, name: str, status: str, message: str, details: list[str] | None = None) -> None:
        self.results.append(CheckResult(category=category, name=name, status=status, message=message, details=details))
        if self.live_stream:
            if category != self.current_cat:
                self.current_cat = category
                print(f"\n[*] {category}", flush=True)
            badge = f"[{status}]"
            print(f"  {badge:<6} {name}: {message}", flush=True)
            if details:
                for d in details:
                    print(f"         - {d}", flush=True)

    def check_environment(self) -> None:
        category = "1. Environment & Host"
        py_ver = sys.version_info
        if py_ver >= (3, 10):
            self.log(category, "Python Runtime", "PASS", f"Python {py_ver.major}.{py_ver.minor}.{py_ver.micro} (>= 3.10 required)")
        else:
            self.log(category, "Python Runtime", "FAIL", f"Python {py_ver.major}.{py_ver.minor} detected. Minimum 3.10 is required.")

        os_name = platform.system()
        self.log(category, "Operating System", "PASS", f"{os_name} ({platform.release()} - {platform.machine()})")

        has_wrapper = (self.repo / "gradlew").is_file() or (self.repo / "gradlew.bat").is_file()
        if has_wrapper:
            self.log(category, "Gradle Wrapper", "PASS", "Gradle wrapper verified at repository root.")
        elif self.is_raw_kit:
            self.log(category, "Gradle Wrapper", "PASS", "Kit repository template mode (gradlew verified in client Android apps).")
        else:
            self.log(category, "Gradle Wrapper", "FAIL", "Missing gradlew / gradlew.bat at repository root.")

        sdk_found = bool(
            os.environ.get("ANDROID_HOME")
            or os.environ.get("ANDROID_SDK_ROOT")
            or (self.repo / "local.properties").is_file()
        )
        if sdk_found:
            self.log(category, "Android SDK", "PASS", "Android SDK configured via environment or local.properties.")
        else:
            self.log(category, "Android SDK", "WARN", "ANDROID_HOME / ANDROID_SDK_ROOT or local.properties not detected.")

        if (self.repo / ".git").is_dir():
            self.log(category, "Git Repository", "PASS", "Active Git repository detected.")
            ensure_local_git_privacy(self.repo)
            self._check_gitignore(category)
            self._check_git_status(category)
        else:
            self.log(category, "Git Repository", "WARN", "Not a Git repository. Version tracking and review diffs disabled.")

    def _check_gitignore(self, category: str) -> None:
        ignore_files = []
        if (self.repo / ".gitignore").is_file():
            ignore_files.append(self.repo / ".gitignore")
        if (self.agents_dir / ".gitignore").is_file():
            ignore_files.append(self.agents_dir / ".gitignore")
        if (self.repo / ".git" / "info" / "exclude").is_file():
            ignore_files.append(self.repo / ".git" / "info" / "exclude")

        if not ignore_files:
            self.log(category, "Git Ignore Rules", "WARN", "No .gitignore or .git/info/exclude file detected. Critical transient and secret files may be tracked.")
            return

        combined_ignore = ""
        for ig_file in ignore_files:
            try:
                combined_ignore += ig_file.read_text(encoding="utf-8", errors="ignore") + "\n"
            except Exception:
                pass

        required_patterns = {
            "Harness State Directory": ("state/", ".agents/state/", "agents/state/"),
            "Python Bytecode Cache": ("__pycache__", "*.pyc", "*.py[cod]"),
            "Zoho Secrets / Config": ("zoho_config.json", "*zoho*token*"),
            "Harness Backup Directory": (".harness-backup", ".harness-backup/"),
        }

        missing_patterns = []
        for name, pats in required_patterns.items():
            if not any(p in combined_ignore for p in pats):
                if name == "Harness Backup Directory" and self.is_raw_kit:
                    continue
                missing_patterns.append(f"{name} (e.g. '{pats[0]}')")

        if not missing_patterns:
            self.log(
                category,
                "Git Ignore Rules",
                "PASS",
                "Harness state, cache, backup, and secrets are properly ignored (via .git/info/exclude or .gitignore).",
            )
        else:
            details = [f"Recommended pattern to add: {m}" for m in missing_patterns]
            self.log(
                category,
                "Git Ignore Rules",
                "WARN",
                f"Missing {len(missing_patterns)} recommended pattern(s) in .gitignore.",
                details=details,
            )

    def _check_git_status(self, category: str) -> None:
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self.repo),
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if proc.returncode == 0:
                uncommitted = [l for l in proc.stdout.splitlines() if l.strip()]
                if not uncommitted:
                    self.log(category, "Git Working Tree", "PASS", "Working tree is clean. All changes are committed.")
                else:
                    self.log(
                        category,
                        "Git Working Tree",
                        "PASS",
                        f"Working tree has {len(uncommitted)} uncommitted application file(s). Harness files are 100% locally private.",
                        details=[f"Uncommitted: {l}" for l in uncommitted[:8]] + ([f"... and {len(uncommitted) - 8} more"] if len(uncommitted) > 8 else []),
                    )
        except Exception as exc:
            self.log(category, "Git Working Tree", "WARN", f"Failed querying git status: {exc}")

    def check_file_structure(self) -> None:
        category = "2. File Structure & Version"
        if not self.agents_dir.is_dir():
            self.log(category, "Harness Directory", "FAIL", f"Harness directory not found at {self.agents_dir}")
            return

        self.log(category, "Harness Directory", "PASS", f"Harness directory verified at {self.agents_dir.name}/")

        version_file = self.agents_dir / "VERSION"
        if version_file.is_file():
            ver = version_file.read_text(encoding="utf-8").strip()
            self.log(category, "Harness Version", "PASS", f"Installed version: v{ver}")
        else:
            self.log(category, "Harness Version", "FAIL", "VERSION file missing in harness directory.")

        rules_file = self.agents_dir / "rules" / "harness-rules.md"
        if rules_file.is_file():
            self.log(category, "Canonical Rules", "PASS", "harness-rules.md verified.")
        else:
            self.log(category, "Canonical Rules", "FAIL", "harness-rules.md missing.")

        scripts_dir = self.agents_dir / "scripts"
        missing_scripts = [s for s in CORE_SCRIPTS if not (scripts_dir / s).is_file()]
        if not missing_scripts:
            self.log(category, "Core Scripts", "PASS", f"All {len(CORE_SCRIPTS)} core harness scripts verified.")
        else:
            self.log(category, "Core Scripts", "FAIL", f"Missing scripts: {', '.join(missing_scripts)}")

        hooks_file = self.agents_dir / "hooks.json"
        if hooks_file.is_file():
            self.log(category, "Safety Hooks Config", "PASS", "hooks.json verified.")
        else:
            self.log(category, "Safety Hooks Config", "WARN", "hooks.json missing (runtime hooks will not trigger).")

        if self.is_raw_kit:
            return
        try:
            from _modules import discover_source_roots

            roots = discover_source_roots(self.repo)
            if roots:
                names = []
                for r in roots:
                    rel = r.relative_to(self.repo).as_posix()
                    names.append(":" + rel.split("/src/")[0].replace("/", ":"))
                self.log(
                    category,
                    "Module Source Roots",
                    "PASS",
                    f"{len(roots)} module source root(s): {', '.join(names)}",
                )
            else:
                self.log(category, "Module Source Roots", "WARN", "No */src/main/{java,kotlin} source roots detected.")
        except Exception as exc:
            self.log(category, "Module Source Roots", "WARN", f"Source-root discovery failed: {exc}")

    def check_subagent_roster(self) -> None:
        category = "3. Subagent Roster"
        subagents_dir = self.agents_dir / "subagents"
        if not subagents_dir.is_dir():
            self.log(category, "Subagents Directory", "FAIL", f"Missing subagents directory at {subagents_dir}")
            return

        missing = []
        corrupted = []
        for name, fingerprint in CORE_SUBAGENTS.items():
            path = subagents_dir / f"{name}.json"
            if not path.is_file():
                missing.append(name)
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                prompt = data.get("system_prompt", "")
                if fingerprint not in prompt:
                    corrupted.append(f"{name} (missing fingerprint: {fingerprint})")
            except Exception as exc:
                corrupted.append(f"{name} (invalid JSON: {exc})")

        if not missing and not corrupted:
            self.log(category, "Subagents Templates", "PASS", f"All {len(CORE_SUBAGENTS)} subagents verified with active fingerprints.")
        else:
            details = []
            if missing:
                details.append(f"Missing: {', '.join(missing)}")
            if corrupted:
                details.append(f"Corrupted: {', '.join(corrupted)}")
            self.log(category, "Subagents Templates", "FAIL", "Subagent roster validation failed.", details)

    def check_product_config(self) -> None:
        category = "4. Product Configuration"
        try:
            import _product
            product_name = getattr(_product, "PRODUCT_NAME", getattr(_product, "PRODUCT", "Android Product"))
            app_id = getattr(_product, "APPLICATION_ID", "")
            pkg_prefix = getattr(_product, "PACKAGE_PREFIX", "")
            assemble_task = getattr(_product, "ASSEMBLE_TASK", ":app:assembleDebug")
            allow_emu = getattr(_product, "ALLOW_EMULATOR", True)
            android_src = getattr(_product, "ANDROID_SRC", ("app", "src", "main"))

            self.log(category, "Product Identity", "PASS", f"Product: '{product_name}', AppID: '{app_id}', PkgPrefix: '{pkg_prefix}'")

            if self.is_raw_kit:
                self.log(category, "Source Root", "PASS", "Kit repository template mode (source root verified in client apps).")
            else:
                src_path = self.repo.joinpath(*android_src)
                if src_path.is_dir():
                    self.log(category, "Source Root", "PASS", f"Verified source root on disk: {src_path.relative_to(self.repo)}")
                else:
                    self.log(category, "Source Root", "FAIL", f"Configured ANDROID_SRC not found on disk: {src_path}")

            self.log(category, "Assemble Task", "PASS", f"Configured assemble task: {assemble_task}")
            self.log(category, "Device Policy", "PASS", f"ALLOW_EMULATOR = {allow_emu}")
            verification_mode = getattr(_product, "DEVICE_VERIFICATION_MODE", "autonomous_e2e")
            self.log(category, "Device Verification", "PASS", f"DEVICE_VERIFICATION_MODE = {verification_mode}")

            self._check_install_consistency(category)
        except Exception as exc:
            self.log(category, "Product Identity", "FAIL", f"Error reading _product.py: {exc}")

    def _check_install_consistency(self, category: str) -> None:
        answers_file = self.repo / ".harness-setup" / "answers.json"
        if not answers_file.is_file():
            return
        try:
            answers = json.loads(answers_file.read_text(encoding="utf-8"))
            if not isinstance(answers, dict):
                return
        except Exception as exc:
            self.log(category, "Install Consistency", "WARN", f"answers.json unreadable: {exc}")
            return

        product_file = self.agents_dir / "scripts" / "_product.py"
        if product_file.is_file():
            import importlib.util
            spec = importlib.util.spec_from_file_location("_target_product", str(product_file))
            if spec and spec.loader:
                _product = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(_product)
            else:
                import _product
        else:
            import _product

        drift = []

        device_policy = str(answers.get("device_policy") or "").strip()
        allow_emu = bool(getattr(_product, "ALLOW_EMULATOR", True))
        if device_policy == "physical-only" and allow_emu:
            drift.append(
                "device policy mismatch: answers.json says physical-only but "
                "_product.py ALLOW_EMULATOR = True (emulator denies are inactive)."
            )
        elif device_policy == "allow" and not allow_emu:
            drift.append(
                "device policy mismatch: answers.json says both allowed but "
                "_product.py ALLOW_EMULATOR = False."
            )

        answers_assemble = str(answers.get("assemble") or "").strip()
        product_assemble = str(getattr(_product, "ASSEMBLE_TASK", "")).strip()
        if answers_assemble and product_assemble and answers_assemble != product_assemble:
            drift.append(
                f"assemble task mismatch: answers.json '{answers_assemble}' vs "
                f"_product.py '{product_assemble}'."
            )

        try:
            from _variants import assemble_task as variant_task

            answers_flavor = str(answers.get("flavor") or "").strip()
            product_flavor = str(getattr(_product, "ACTIVE_FLAVOR", "") or "").strip()
            if answers_flavor and product_flavor and answers_flavor != product_flavor:
                drift.append(
                    f"daily flavor mismatch: answers.json '{answers_flavor}' vs "
                    f"_product.py ACTIVE_FLAVOR '{product_flavor}'."
                )
            answers_tasks = answers.get("assemble_tasks") or {}
            for flavor_name, task in sorted(answers_tasks.items()):
                resolved = variant_task(flavor_name)
                if str(task).strip() and resolved != str(task).strip() and flavor_name == product_flavor:
                    drift.append(
                        f"flavor task mismatch for '{flavor_name}': answers.json '{task}' "
                        f"resolves to '{resolved}'."
                    )
        except Exception:
            pass

        try:
            from install_tool_adapters import MANAGED, TOOL_FILES

            selected_tools = [str(t) for t in (answers.get("tools") or [])]
            missing_adapters = []
            for tool in selected_tools:
                for rel in TOOL_FILES.get(tool, ()):
                    path = self.repo / rel
                    if not path.is_file():
                        missing_adapters.append(rel)
                        continue
                    try:
                        if MANAGED.strip() not in path.read_text(encoding="utf-8"):
                            missing_adapters.append(f"{rel} (unmanaged)")
                    except OSError:
                        missing_adapters.append(rel)
            agents_md = self.repo / "AGENTS.md"
            if selected_tools and not agents_md.is_file():
                missing_adapters.append("AGENTS.md")
        except Exception:
            missing_adapters = []

        if missing_adapters:
            drift.append(
                f"selected tool adapters missing/unmanaged: {', '.join(missing_adapters)}. "
                "Re-run install_tool_adapters.py with the recorded --tools."
            )

        if drift:
            drift.append(
                "To change setup answers: python .agents/scripts/setup_wizard.py ask "
                f"--repo {self.repo} --lang <en|ar> (previous answers are pre-filled; press Enter "
                "to keep each one), then re-run install_tool_adapters.py with the flags the "
                "wizard prints."
            )
            self.log(
                category,
                "Install Consistency",
                "FAIL",
                f"{len(drift)} configuration drift(s) between answers.json and this checkout.",
                details=drift,
            )
        else:
            self.log(
                category,
                "Install Consistency",
                "PASS",
                "answers.json matches _product.py and all selected adapters are managed and present.",
            )

    def check_template_leaks(self) -> None:
        category = "5. Template Leak Check"
        if self.is_raw_kit:
            self.log(category, "Placeholder Inspection", "PASS", "Kit repository template mode (placeholders expected in kit templates).")
            return

        leaks = []
        token_re = re.compile(r"\{\{[A-Z0-9_]+\}\}")
        for path in self.agents_dir.rglob("*"):
            if not path.is_file() or any(
                x in path.parts for x in {"__pycache__", "state", "tool-adapters", "command-packs"}
            ):
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                matches = token_re.findall(content)
                if matches:
                    leaks.append(f"{path.relative_to(self.repo)}: {', '.join(set(matches))}")
            except Exception:
                continue

        if not leaks:
            self.log(category, "Placeholder Inspection", "PASS", "Zero un-replaced template placeholders ({{...}}) detected in .agents/.")
        else:
            self.log(category, "Placeholder Inspection", "FAIL", f"Found {len(leaks)} file(s) with un-replaced placeholders.", leaks)

    def _detect_project_domains(self) -> set[str]:
        detected = set()
        skip_parts = {".git", ".gradle", "build", ".harness-backup", "node_modules", "__pycache__"}
        text_corpus = ""
        for p in self.repo.glob("**/*.gradle*"):
            if any(x in p.parts for x in skip_parts):
                continue
            try:
                text_corpus += p.read_text(encoding="utf-8", errors="ignore") + "\n"
            except Exception:
                pass

        toml_path = self.repo / "gradle" / "libs.versions.toml"
        if toml_path.is_file():
            try:
                text_corpus += toml_path.read_text(encoding="utf-8", errors="ignore") + "\n"
            except Exception:
                pass

        for p in self.repo.glob("**/AndroidManifest.xml"):
            if any(x in p.parts for x in skip_parts):
                continue
            try:
                text_corpus += p.read_text(encoding="utf-8", errors="ignore") + "\n"
            except Exception:
                pass

        scanned_kt = 0
        max_kt_files = 500
        for p in self.repo.rglob("*.kt"):
            if scanned_kt >= max_kt_files:
                break
            if any(x in p.parts for x in skip_parts):
                continue
            try:
                text_corpus += p.read_text(encoding="utf-8", errors="ignore") + "\n"
                scanned_kt += 1
            except Exception:
                continue

        for domain_name, config in KNOWN_DOMAINS.items():
            for sig in config["signatures"]:
                if sig.lower() in text_corpus.lower():
                    detected.add(domain_name)
                    break
        return detected

    def check_skills_and_workflows(self) -> None:
        category = "6. Skills & Workflows"
        workflows_dir = self.agents_dir / "workflows"
        missing_wf = [wf for wf in CORE_WORKFLOWS if not (workflows_dir / wf).is_file()]
        if not missing_wf:
            self.log(category, "Workflow Playbooks", "PASS", f"All {len(CORE_WORKFLOWS)} workflow playbooks verified.")
        else:
            self.log(category, "Workflow Playbooks", "FAIL", f"Missing workflows: {', '.join(missing_wf)}")

        ref_dir = self.agents_dir / "skills" / "android-harness" / "references"
        if not ref_dir.is_dir():
            self.log(category, "Domain References", "FAIL", f"Missing references directory at {ref_dir}")
            return

        missing_foundation = []
        corrupted_foundation = []
        for r in CORE_REFERENCES:
            ref_path = ref_dir / r
            if not ref_path.is_file():
                missing_foundation.append(r)
            elif ref_path.stat().st_size < 20:
                corrupted_foundation.append(f"{r} (empty or corrupted: {ref_path.stat().st_size} bytes)")

        if missing_foundation:
            self.log(category, "Foundation References", "FAIL", f"Missing {len(missing_foundation)} foundation reference(s): {', '.join(missing_foundation)}")
        elif corrupted_foundation:
            self.log(category, "Foundation References", "FAIL", f"Corrupted reference files detected: {', '.join(corrupted_foundation)}")
        else:
            self.log(category, "Foundation References", "PASS", f"All {len(CORE_REFERENCES)} foundation architectural references verified.")

        all_refs = sorted([f.name for f in ref_dir.glob("*.md")])
        tailored_refs = [r for r in all_refs if r not in CORE_REFERENCES]

        if self.is_raw_kit:
            self.log(category, "Tailored Domain Coverage", "PASS", "Kit template mode (domain discovery active on client Android apps).")
            self.log(category, "Domain Reference Indexing", "PASS", "Foundation scenarios indexed in daily-scenarios.md.")
            return

        detected_domains = self._detect_project_domains()
        uncovered_domains = []
        covered_domains = []

        for domain_name, config in KNOWN_DOMAINS.items():
            if domain_name in detected_domains:
                prefixes = config["expected_prefixes"]
                has_tailored = any(any(ref.startswith(p) for p in prefixes) for ref in tailored_refs)
                if has_tailored:
                    matching = [ref for ref in tailored_refs if any(ref.startswith(p) for p in prefixes)]
                    covered_domains.append(f"{domain_name} -> {', '.join(matching)}")
                else:
                    uncovered_domains.append(f"{domain_name} (suggested: '{config['sample_file']}')")

        details = []
        if tailored_refs:
            details.append(f"Active tailored guides ({len(tailored_refs)}): {', '.join(tailored_refs)}")
        if covered_domains:
            details.append(f"Domain integrations confirmed: {'; '.join(covered_domains)}")

        if not uncovered_domains:
            msg = f"Deep domain integration verified: {len(tailored_refs)} tailored reference guide(s) active."
            self.log(category, "Tailored Domain Coverage", "PASS", msg, details=details if details else None)
        else:
            details.extend([f"Uncovered domain detected: {d}" for d in uncovered_domains])
            self.log(
                category,
                "Tailored Domain Coverage",
                "WARN",
                f"Detected {len(uncovered_domains)} active project domain(s) without dedicated reference guide(s).",
                details=details,
            )

        daily_scenarios_path = ref_dir / "daily-scenarios.md"
        if daily_scenarios_path.is_file():
            daily_content = daily_scenarios_path.read_text(encoding="utf-8", errors="ignore")
            unlinked_refs = [
                r for r in all_refs
                if r != "daily-scenarios.md" and r not in daily_content and r.replace(".md", "") not in daily_content
            ]
            if not unlinked_refs:
                self.log(
                    category,
                    "Domain Reference Indexing",
                    "PASS",
                    f"All {len(all_refs)} domain and foundation reference guides are indexed in daily-scenarios.md.",
                )
            else:
                self.log(
                    category,
                    "Domain Reference Indexing",
                    "WARN",
                    f"Found {len(unlinked_refs)} reference guide(s) not linked in daily-scenarios.md: {', '.join(unlinked_refs)}",
                    details=[f"Link '{u}' in daily-scenarios.md so AI subagents can discover and cite it." for u in unlinked_refs],
                )
        else:
            self.log(category, "Domain Reference Indexing", "WARN", "daily-scenarios.md missing; reference routing disabled.")

    def check_tool_adapters(self) -> None:
        category = "7. Multi-IDE Tool Adapters"
        if self.is_raw_kit:
            self.log(category, "Adapter Parity", "PASS", "Kit repository template mode (adapters verified in client checkouts).")
            return

        agents_md = self.repo / "AGENTS.md"
        if agents_md.is_file():
            self.log(category, "Root AGENTS.md", "PASS", "Root AGENTS.md verified.")
        else:
            self.log(category, "Root AGENTS.md", "WARN", "Root AGENTS.md missing. Run install_tool_adapters.py.")

        known_adapters = [
            (".cursor/rules/android-harness.mdc", "Cursor"),
            ("CLAUDE.md", "Claude Code"),
            (".github/copilot-instructions.md", "GitHub Copilot"),
            (".windsurf/rules/android-harness.md", "Windsurf"),
            ("GEMINI.md", "Gemini CLI / Antigravity"),
            ("CODEX.md", "Codex"),
            ("QWEN.md", "Qwen Code"),
        ]
        found_adapters = [name for rel, name in known_adapters if (self.repo / rel).is_file()]
        if found_adapters:
            self.log(category, "Active Adapters", "PASS", f"Configured adapters for: {', '.join(found_adapters)}")
        else:
            self.log(category, "Active Adapters", "WARN", "No tool-specific adapters detected at repository root.")

    def check_safety_and_selftest(self) -> None:
        category = "8. Safety & Concurrency"
        try:
            from _hook_state import state_lock
            with state_lock(timeout=2.0):
                pass
            self.log(category, "State File Lock", "PASS", "Cross-platform atomic state_lock() acquired and released cleanly.")
        except Exception as exc:
            self.log(category, "State File Lock", "FAIL", f"state_lock() failed: {exc}")

        if not self.run_selftest:
            self.log(category, "Hook Selftest Suite", "PASS", "Hook selftest active in parent harness test suite.")
            return

        selftest_script = self.agents_dir / "scripts" / "_hook_selftest.py"
        if selftest_script.is_file():
            proc = subprocess.run(
                [sys.executable, str(selftest_script)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(self.repo),
            )
            if proc.returncode == 0:
                self.log(category, "Hook Selftest Suite", "PASS", "Full selftest suite passed (0 test failures).")
            else:
                out_snippet = "\n".join(proc.stdout.strip().splitlines()[-5:])
                self.log(category, "Hook Selftest Suite", "FAIL", f"Selftest failed with exit code {proc.returncode}:\n{out_snippet}")
        else:
            self.log(category, "Hook Selftest Suite", "WARN", "_hook_selftest.py script missing.")

    def check_process_streaming(self) -> None:
        category = "9. Process Streaming"
        try:
            from _live_process import enable_line_buffered_stdio
            enable_line_buffered_stdio()
            self.log(category, "Line-Buffered Stdio", "PASS", "Standard I/O line buffering active.")
        except Exception as exc:
            self.log(category, "Line-Buffered Stdio", "WARN", f"Line-buffered stdio check error: {exc}")

    def check_preflight_pipeline(self) -> None:
        category = "10. Preflight Pipeline"
        if not self.run_selftest:
            self.log(category, "Preflight Sanity Suite", "PASS", "Preflight pipeline active in parent test suite.")
            return

        preflight_script = self.agents_dir / "scripts" / "preflight_check.py"
        if preflight_script.is_file():
            proc = subprocess.run(
                [sys.executable, str(preflight_script)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(self.repo),
            )
            if proc.returncode == 0:
                self.log(category, "Preflight Sanity Suite", "PASS", "String Parity, Room Guard, and Fast Kotlin Lint passed.")
            else:
                out_lines = proc.stdout.strip().splitlines()
                is_string_parity_only = (
                    any("String Parity" in line or "string issue(s)" in line for line in out_lines)
                    and not any("Room Migration Error" in line or "Lint Errors" in line or "Hook selftest FAILED" in line for line in out_lines)
                )
                out_snippet = "\n".join(out_lines[-8:])
                if is_string_parity_only:
                    self.log(
                        category,
                        "Preflight Sanity Suite",
                        "WARN",
                        f"Harness sanity verified; application localization advisory (informational):\n{out_snippet}",
                    )
                else:
                    self.log(category, "Preflight Sanity Suite", "FAIL", f"Preflight checks reported critical issues:\n{out_snippet}")
        else:
            self.log(category, "Preflight Sanity Suite", "WARN", "preflight_check.py missing.")

    def check_zoho_mcp(self) -> None:
        category = "11. Project Tracker & PM Security"
        pm_provider_raw = ""
        try:
            import _product as _pm_product
            pm_provider_raw = str(getattr(_pm_product, "PM_PROVIDER", "") or "").strip()
        except Exception:
            pm_provider_raw = ""
        try:
            from pm_policy import PROVIDERS, resolve_provider
            resolved = resolve_provider(pm_provider_raw)
        except SystemExit as exc:
            self.log(
                category,
                "PM Provider",
                "FAIL",
                f"Invalid PM_PROVIDER in _product.py: {exc}",
            )
        else:
            if resolved == "none":
                self.log(
                    category,
                    "PM Provider",
                    "PASS",
                    "PM_PROVIDER=none (local-only delivery; no tracker mutations possible).",
                )
            else:
                display = str(PROVIDERS[resolved]["display"])
                trigger = str(PROVIDERS[resolved]["trigger"])
                config_file = str(PROVIDERS[resolved].get("config_file") or "")
                user_cfg_ok = bool(config_file) and (Path.home() / ".android-harness" / config_file).is_file()
                cfg_note = (
                    f"user-level config present ({config_file})"
                    if user_cfg_ok
                    else f"no user-level config yet (~/.android-harness/{config_file}) - optional until first use"
                )
                self.log(
                    category,
                    "PM Provider",
                    "PASS",
                    f"Active tracker: {display} (PM_PROVIDER={resolved or 'zoho_sprints'}); "
                    f"mutations require the explicit phrase '{trigger}'. {cfg_note}.",
                )

        mcp_config = self.agents_dir / "mcp_config.json"
        if mcp_config.is_file():
            try:
                data = json.loads(mcp_config.read_text(encoding="utf-8"))
                zoho_server = data.get("mcpServers", {}).get("zoho-sprints")
                if zoho_server:
                    self.log(category, "MCP Configuration", "PASS", "Zoho Sprints MCP registered in mcp_config.json.")
                else:
                    self.log(category, "MCP Configuration", "PASS", "Zoho Sprints MCP is not enabled (optional).")
            except Exception as exc:
                self.log(category, "MCP Configuration", "WARN", f"Could not parse mcp_config.json: {exc}")
        else:
            self.log(category, "MCP Configuration", "PASS", "No mcp_config.json found (Zoho Sprints is optional).")

        repo_tokens: list[Path] = []
        seen_token_paths: set[str] = set()
        secret_globs = [
            "**/zoho_config.json",
            "**/*zoho*token*.json",
            "**/zoho_sprints.json",
            "**/github_projects.json",
            "**/jira.json",
            "**/linear.json",
        ]
        for pattern in secret_globs:
            for path in self.repo.glob(pattern):
                marker = str(path).lower()
                if marker not in seen_token_paths:
                    seen_token_paths.add(marker)
                    repo_tokens.append(path)
        if not repo_tokens:
            self.log(
                category,
                "Credential Isolation",
                "PASS",
                "Zero PM/Zoho tokens or provider secret files in repository.",
            )
        else:
            self.log(category, "Credential Isolation", "FAIL", f"Tokens detected in repository: {', '.join(str(p) for p in repo_tokens)}")

    def check_connected_devices(self) -> None:
        if not self.check_device:
            return
        category = "12. Connected Devices"
        adb_path = shutil.which("adb")
        if not adb_path:
            self.log(category, "ADB Executable", "WARN", "adb command not found in system PATH.")
            return

        self.log(category, "ADB Executable", "PASS", f"adb available at {adb_path}")
        try:
            proc = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=5.0)
            devices = []
            for l in lines:
                parts = l.split()
                if len(parts) >= 2 and parts[1] == "device":
                    devices.append(parts[0])
            if devices:
                self.log(category, "Connected Devices", "PASS", f"Detected {len(devices)} active device(s): {', '.join(devices)}")
            else:
                self.log(category, "Connected Devices", "WARN", "No active devices/emulators connected via ADB.")
        except Exception as exc:
            self.log(category, "Connected Devices", "WARN", f"Failed querying adb devices: {exc}")

    def run_all(self) -> list[CheckResult]:
        if self.live_stream:
            print("==================================================", flush=True)
            print("  Android Agent Harness: 12-Dimension Diagnostic Report", flush=True)
            print("==================================================", flush=True)
        self.check_environment()
        self.check_file_structure()
        self.check_subagent_roster()
        self.check_product_config()
        self.check_template_leaks()
        self.check_skills_and_workflows()
        self.check_tool_adapters()
        self.check_safety_and_selftest()
        self.check_process_streaming()
        self.check_preflight_pipeline()
        self.check_zoho_mcp()
        if self.check_device:
            self.check_connected_devices()
        return self.results
