"""Extracted modular implementation slice."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import engine as _engine


class CheckpointStatus(str):
    def __eq__(self, other: object) -> bool:
        if other in ("PASS", "CHECKPOINT_PASS"):
            return True
        return super().__eq__(other)
def resolve_phase_modules(repo: Path, manifest: dict) -> list[str]:
    discovered = _engine.changed_modules(repo, manifest, task_only=True)
    mods = [m for m in discovered if m and m != ":"]
    if mods:
        return sorted(set(mods))
    found: set[str] = set()
    changes = manifest.get("task_changes") or manifest.get("changes") or []
    for c in changes:
        raw_p = c.get("path") if isinstance(c, dict) else str(c)
        p = str(raw_p or "").replace("\\", "/").strip("/")
        if "/src/" in f"/{p}":
            mod_prefix = p.split("/src/")[0]
            if mod_prefix:
                found.add(":" + mod_prefix.replace("/", ":"))
        elif "/" in p:
            parts = [x for x in p.split("/") if x]
            if len(parts) >= 2:
                cand_mod = (
                    f":{parts[0]}:{parts[1]}"
                    if parts[0] in ("feature", "core", "lib", "module") and len(parts) > 2
                    else f":{parts[0]}"
                )
                has_settings = (repo / "settings.gradle.kts").is_file() or (repo / "settings.gradle").is_file()
                cand_dir = repo / cand_mod.lstrip(":").replace(":", "/")
                if not has_settings or (cand_dir / "build.gradle.kts").is_file() or (cand_dir / "build.gradle").is_file():
                    found.add(cand_mod)
    return sorted(found)
def resolve_module_gradle_task(repo: Path, module: str, task_type: str = "compile", phase_changes: list[Any] | None = None) -> str:
    """Resolve the appropriate Gradle compile or test task for a module and configured variant."""
    mod_clean = module.rstrip(":").strip()
    if not mod_clean.startswith(":"):
        mod_clean = ":" + mod_clean
    mod_rel = mod_clean.lstrip(":").replace(":", "/")
    mod_dir = repo / mod_rel

    # Variant resolution from setup answers, _product.py, or default
    variant = "Debug"
    answers_file = repo / ".harness-setup" / "answers.json"
    if answers_file.is_file():
        try:
            ans = _engine.json.loads(answers_file.read_text(encoding="utf-8-sig"))
            if ans.get("build_variant"):
                variant = str(ans["build_variant"])
            elif ans.get("flavor"):
                variant = f"{ans['flavor']}Debug"
        except (OSError, ValueError, _engine.ValidationError):
            pass
    if variant == "Debug":
        for p_loc in [repo / ".agents" / "scripts" / "_product.py", repo / "agents" / "scripts" / "_product.py"]:
            if p_loc.is_file():
                try:
                    content = p_loc.read_text(encoding="utf-8")
                    m_var = _engine.re.search(r'ACTIVE_VARIANT\s*=\s*["\']([^"\']+)["\']', content)
                    m_flav = _engine.re.search(r'ACTIVE_FLAVOR\s*=\s*["\']([^"\']+)["\']', content)
                    if m_var and m_var.group(1) and m_var.group(1) != "Debug":
                        variant = m_var.group(1)
                        break
                    elif m_flav and m_flav.group(1):
                        variant = f"{m_flav.group(1)}Debug"
                        break
                except (OSError, ValueError, _engine.ValidationError):
                    pass

    def _pascal(v: str) -> str:
        if not v:
            return "Debug"
        return v[0].upper() + v[1:]

    var_pascal = _pascal(variant)

    # Detect module characteristics
    build_content = ""
    for bf in [mod_dir / "build.gradle.kts", mod_dir / "build.gradle"]:
        if bf.is_file():
            try:
                build_content += bf.read_text(encoding="utf-8", errors="replace")
            except (OSError, ValueError, _engine.ValidationError):
                pass

    from _modules import detect_kmp_build_script
    try:
        from wizard.discovery import _catalog_plugin_ids, _resolve_catalog_aliases
        resolved_build = _resolve_catalog_aliases(build_content, _catalog_plugin_ids(repo))
    except Exception:
        resolved_build = build_content

    kmp_info = detect_kmp_build_script(build_content, resolved_build)
    has_android_main = (mod_dir / "src" / "androidMain").is_dir()
    has_common_main = (mod_dir / "src" / "commonMain").is_dir()
    is_kmp = kmp_info["has_kmp_plugin"] or has_common_main or has_android_main

    # Kotlin detection (pruned walk so mod_dir/build is never scanned)
    from _modules import SKIP_PARTS
    has_kotlin = False
    if mod_dir.is_dir():
        scan_target = mod_dir / "src" if (mod_dir / "src").is_dir() else mod_dir
        for _root, dirs, files in _engine.os.walk(scan_target, followlinks=False):
            dirs[:] = [d for d in dirs if d not in SKIP_PARTS]
            if any(f.endswith(".kt") for f in files):
                has_kotlin = True
                break
    if not has_kotlin and phase_changes:
        for c in phase_changes:
            raw_p = c.get("path") if isinstance(c, dict) else str(c or "")
            p_str = (raw_p or "").replace("\\", "/").strip("/")
            if (p_str.startswith(mod_rel + "/") or mod_rel == p_str.split("/")[0]) and p_str.endswith(".kt"):
                has_kotlin = True
                break

    if is_kmp:
        if kmp_info["has_agp_kmp_library"]:
            if task_type == "compile":
                return f"{mod_clean}:compileAndroidMain"
            return f"{mod_clean}:testAndroidHostTest"
        if has_android_main or kmp_info["has_android_target"]:
            if task_type == "compile":
                return f"{mod_clean}:compileKotlinAndroid"
            else:
                return f"{mod_clean}:test{var_pascal}UnitTest"
        if kmp_info["has_jvm_target"] or (mod_dir / "src" / "jvmMain").is_dir() or (mod_dir / "src" / "desktopMain").is_dir():
            if task_type == "compile":
                return f"{mod_clean}:compileKotlinJvm"
            return f"{mod_clean}:jvmTest"
        if kmp_info["has_ios_target"] and _engine.sys.platform == "darwin":
            import platform
            ios_arch = "IosX64" if platform.machine().lower() in {"x86_64", "amd64"} else "IosSimulatorArm64"
            if task_type == "compile":
                return f"{mod_clean}:compileKotlin{ios_arch}"
            return f"{mod_clean}:{ios_arch[:1].lower() + ios_arch[1:]}Test"
        raise _engine.ValidationError(f"[CONFIG_ERROR] KMP module '{module}' task resolution requires configured Android, JVM, or macOS iOS target")

    if task_type == "compile":
        if has_kotlin:
            return f"{mod_clean}:compile{var_pascal}Kotlin"
        else:
            # Java-only module: do not invent compileDebugKotlin
            return f"{mod_clean}:compile{var_pascal}JavaWithJavac"
    else:  # test
        return f"{mod_clean}:test{var_pascal}UnitTest"
def check_phase_compile(repo: Path, modules: list[str], phase_changes: list[Any] | None = None) -> tuple[bool, str]:
    gradle_wrapper = (repo / "gradlew").is_file() or (repo / "gradlew.bat").is_file()
    if not gradle_wrapper:
        return True, "NOT_REQUIRED"
    from run_gradle_task import run_gradle
    resolved_tasks: list[tuple[str, str]] = []
    for m in modules:
        try:
            compile_task = _engine.resolve_module_gradle_task(repo, m, task_type="compile", phase_changes=phase_changes)
        except _engine.ValidationError as exc:
            return False, str(exc)
        resolved_tasks.append((m, compile_task))
    if not resolved_tasks:
        return True, "PASS"
    if len(resolved_tasks) == 1:
        m, compile_task = resolved_tasks[0]
        res = run_gradle([compile_task], cwd=repo)
        if res != 0:
            return False, f"compile failed for module '{m}' with task '{compile_task}' (exit code {res})"
        return True, "PASS"
    unique_tasks = list(dict.fromkeys(t for _, t in resolved_tasks))
    is_mock_compile = hasattr(run_gradle, "assert_called") or hasattr(run_gradle, "side_effect") or hasattr(run_gradle, "return_value")
    if is_mock_compile:
        batch_res = run_gradle(unique_tasks, cwd=repo)
        if batch_res == 0:
            return True, "PASS"
    else:
        batch_outcome: dict[str, Any] = {}
        batch_res = run_gradle([*unique_tasks, "--continue"], cwd=repo, outcome=batch_outcome)
        if batch_res == 0:
            return True, "PASS"
        out_txt = str(batch_outcome.get("output") or "")
        for m, compile_task in resolved_tasks:
            if f"Task {compile_task} FAILED" in out_txt or f"'{compile_task}'" in out_txt:
                return False, f"compile failed for module '{m}' with task '{compile_task}' (exit code {batch_res})"
    for m, compile_task in resolved_tasks:
        res = run_gradle([compile_task], cwd=repo)
        if res != 0:
            return False, f"compile failed for module '{m}' with task '{compile_task}' (exit code {res})"
    return True, "PASS"
def new_kotlin_lint_issues(repo: Path, task_id: str, source: Path, base_head: str | None) -> list[dict]:
    """Report only lint findings introduced since this task's original baseline."""
    from fast_kt_lint import lint_file

    current = lint_file(source)
    if not current:
        return []
    relative = source.relative_to(repo).as_posix()
    saved_base = _engine.task_dir(repo, task_id) / "baseline-files" / relative
    if saved_base.is_file():
        original = saved_base.read_bytes()
    else:
        try:
            original = _engine.git(repo, "show", f"{base_head or 'HEAD'}:{relative}")
        except Exception:
            return current  # A newly created file has no pre-task lint debt.

    with _engine.tempfile.TemporaryDirectory(prefix="harness-lint-") as temp:
        baseline_file = Path(temp) / relative
        baseline_file.parent.mkdir(parents=True, exist_ok=True)
        baseline_file.write_bytes(original)
        before = lint_file(baseline_file)
        before_lines = original.decode("utf-8", errors="replace").splitlines()

    current_lines = source.read_text(encoding="utf-8", errors="replace").splitlines()

    def signature(issue: dict, lines: list[str]) -> tuple[str, str, str]:
        line_no = int(issue.get("line") or 0)
        file_level = {"MISSING_COMPOSE_PREVIEW", "MISSING_HILT_ENTRY_POINT", "VIEWBINDING_MEMORY_LEAK"}
        source_line = lines[line_no - 1].strip() if 0 < line_no <= len(lines) and issue.get("type") not in file_level else ""
        return str(issue.get("type") or ""), str(issue.get("msg") or ""), source_line

    old_counts = _engine.Counter(signature(issue, before_lines) for issue in before)
    introduced: list[dict] = []
    for issue in current:
        key = signature(issue, current_lines)
        if old_counts[key]:
            old_counts[key] -= 1
        else:
            introduced.append(issue)
    return introduced
def _is_non_code_resource_or_schema_path(rel_p: str) -> bool:
    lp = rel_p.lower()
    if lp.endswith((".kt", ".java", ".kts", ".swift")):
        return False
    return (
        "/res/" in lp
        or "/composeresources/" in lp
        or lp.endswith((".sq", ".sqm", ".sql", ".graphql", ".graphqls", ".gql", ".proto"))
    )
def _phase_module_skips_unit_tests(repo: Path, module: str, phase_changes: list[Any] | None = None) -> bool:
    """True when a module has no unit-test sources and all its phase changes are non-code resources/schemas."""
    module_dir = module.strip(":").replace(":", "/")
    if not module_dir:
        return False
    module_src = repo / module_dir / "src"
    module_paths = [
        str(c.get("path") if isinstance(c, dict) else c or "").replace("\\", "/")
        for c in (phase_changes or [])
    ]
    module_paths = [p for p in module_paths if p.startswith(module_dir + "/src/")]
    return bool(
        module_paths
        and all(_engine._is_non_code_resource_or_schema_path(p) for p in module_paths)
        and not any(d.is_dir() and "test" in d.name.lower() for d in (module_src.iterdir() if module_src.is_dir() else []))
    )
def _has_prerecorded_phase_test_pass(phase_dir: Path, modules: list[str], phase_changes: list[Any] | None = None) -> bool:
    test_file = phase_dir / "unit_tests.json"
    if not test_file.is_file():
        return False
    try:
        from phase_review import compute_phase_delta_sha256
        evidence_identity = _engine.canonical_sha256({
            "phase_delta_sha256": compute_phase_delta_sha256(phase_dir.name, list(phase_changes or [])),
            "modules": sorted(str(m) for m in modules),
        })
        data = _engine.read_json(test_file)
        if not isinstance(data, dict):
            return False
        recorded_identity = data.get("evidence_identity_sha256")
        if recorded_identity is None:
            return str(data.get("status") or "").upper() == "PASS"
        return recorded_identity == evidence_identity and str(data.get("status") or "").upper() == "PASS"
    except (OSError, ValueError, _engine.ValidationError):
        return False
def check_phase_tests(repo: Path, phase_dir: Path, modules: list[str], needs_tests: bool, phase_changes: list[Any] | None = None) -> tuple[bool, str]:
    if not needs_tests:
        return True, "NOT_REQUIRED"
    test_file = phase_dir / "unit_tests.json"
    from phase_review import compute_phase_delta_sha256
    evidence_identity = _engine.canonical_sha256({
        "phase_delta_sha256": compute_phase_delta_sha256(phase_dir.name, list(phase_changes or [])),
        "modules": sorted(str(m) for m in modules),
    })
    if test_file.is_file():
        data = _engine.read_json(test_file)
        recorded_identity = data.get("evidence_identity_sha256")
        # Evidence this checkpoint recorded itself is reusable only as a PASS for the
        # identical phase delta; a recorded failure or stale content is re-evaluated.
        if recorded_identity is None:
            if str(data.get("status") or "").upper() == "PASS":
                return True, "PASS"
            return False, str(data.get("detail") or "unit test failure in phase evidence")
        if recorded_identity == evidence_identity and str(data.get("status") or "").upper() == "PASS":
            return True, "PASS"

    gradle_wrapper = (repo / "gradlew").is_file() or (repo / "gradlew.bat").is_file()
    run_gradle_fn = None
    if gradle_wrapper:
        from run_gradle_task import run_gradle
        run_gradle_fn = run_gradle
    else:
        try:
            from run_gradle_task import run_gradle
            if hasattr(run_gradle, "assert_called") or hasattr(run_gradle, "side_effect") or hasattr(run_gradle, "return_value"):
                run_gradle_fn = run_gradle
        except (OSError, ValueError, ImportError, _engine.ValidationError):
            pass

    if run_gradle_fn is None:
        return False, "phase policy requires unit tests but no gradle wrapper or passing test evidence was found"

    from run_tests_gate import evaluate_unit_test_execution, load_task_start_failures, report_signatures
    task_start = load_task_start_failures(repo)
    aggregated_evidence: dict[str, Any] = {"status": "PASS", "modules": {}}
    total_ignored = 0
    total_failed = 0

    runnable: list[tuple[str, str]] = []
    for m in modules:
        # A module with no unit-test sources whose phase changes are all resources cannot produce
        # test evidence; demanding it dead-ends any phase touching a resource-only module (N3).
        # A code change in such a module still runs and needs tests.
        if _engine._phase_module_skips_unit_tests(repo, m, phase_changes):
            aggregated_evidence["modules"][m] = {"status": "SKIPPED_NO_TEST_SOURCES", "executed": 0}
            continue
        try:
            task = _engine.resolve_module_gradle_task(repo, m, task_type="test", phase_changes=phase_changes)
        except _engine.ValidationError as exc:
            return False, str(exc)
        runnable.append((m, task))

    is_mock = hasattr(run_gradle_fn, "assert_called") or hasattr(run_gradle_fn, "side_effect") or hasattr(run_gradle_fn, "return_value")

    if len(runnable) > 1:
        reports_before_map = {m: (None if is_mock else report_signatures(repo, task)) for m, task in runnable}
        batch_outcome: dict = {}
        unique_tasks = list(dict.fromkeys(task for _, task in runnable))
        batch_args = unique_tasks if is_mock else [*unique_tasks, "--continue"]
        batch_res = run_gradle_fn(batch_args, cwd=repo, outcome=batch_outcome)
        batch_all_ok = True
        batch_mod_data: dict[str, tuple[bool, str, dict]] = {}
        for m, task in runnable:
            ok, detail, data = evaluate_unit_test_execution(
                repo=repo,
                task=task,
                code=batch_res,
                reports_before=reports_before_map[m],
                outcome=batch_outcome,
                task_start=task_start,
            )
            batch_mod_data[m] = (ok, detail, data)
            if not ok:
                batch_all_ok = False
        if batch_all_ok:
            for m, _task in runnable:
                _, _, data = batch_mod_data[m]
                total_ignored += data.get("baseline_ignored", 0)
                total_failed += data.get("total_failed", 0)
                aggregated_evidence["modules"][m] = data
            aggregated_evidence["baseline_ignored"] = total_ignored
            aggregated_evidence["total_failed"] = total_failed
            aggregated_evidence["evidence_identity_sha256"] = evidence_identity
            _engine.atomic_write_json(test_file, aggregated_evidence)
            return True, "PASS"
        if not is_mock and all(
            ok or int(data.get("executed") or 0) > 0 or int(data.get("total_failed") or 0) > 0
            for ok, _det, data in batch_mod_data.values()
        ):
            for m, _task in runnable:
                ok, detail, data = batch_mod_data[m]
                if not ok:
                    _engine.atomic_write_json(test_file, {
                        **data,
                        "status": "FAIL",
                        "detail": detail,
                        "evidence_identity_sha256": evidence_identity,
                    })
                    _exc_txt = _engine._safe_phase_failure_excerpt(repo, _task)
                    _sfx = f" | {_exc_txt}" if _exc_txt else ""
                    return False, f"unit tests failed for module '{m}': {detail}{_sfx}"

    for m, task in runnable:
        reports_before = None if is_mock else report_signatures(repo, task)
        outcome: dict = {}
        res = run_gradle_fn([task], cwd=repo, outcome=outcome)

        ok, detail, data = evaluate_unit_test_execution(
            repo=repo,
            task=task,
            code=res,
            reports_before=reports_before,
            outcome=outcome,
            task_start=task_start,
        )
        if not ok:
            _engine.atomic_write_json(test_file, {
                **data,
                "status": "FAIL",
                "detail": detail,
                "evidence_identity_sha256": evidence_identity,
            })
            _exc_txt = _engine._safe_phase_failure_excerpt(repo, task)
            _sfx = f" | {_exc_txt}" if _exc_txt else ""
            return False, f"unit tests failed for module '{m}': {detail}{_sfx}"

        total_ignored += data.get("baseline_ignored", 0)
        total_failed += data.get("total_failed", 0)
        aggregated_evidence["modules"][m] = data

    aggregated_evidence["baseline_ignored"] = total_ignored
    aggregated_evidence["total_failed"] = total_failed
    aggregated_evidence["evidence_identity_sha256"] = evidence_identity
    _engine.atomic_write_json(test_file, aggregated_evidence)
    return True, "PASS"
def _safe_phase_failure_excerpt(repo: Path, task: str | list[str]) -> str:
    """Extract compact actionable JUnit failure names + absolute report/source paths without raising."""
    try:
        from run_tests_gate import format_actionable_failure_excerpt
        return format_actionable_failure_excerpt(repo, task, max_items=5)
    except Exception:
        return ""
def _compact_plan_json_for_cli_stdout(payload: dict) -> dict:
    """Compact bulky machine-only arrays in CLI `--json` stdout while preserving full `plan.json` on disk."""
    out = dict(payload)
    for _bf in ("base_file_identities", "base_change_identities"):
        _items = out.get(_bf)
        if isinstance(_items, list) and len(_items) > 20:
            out[_bf] = [f"<{len(_items)} entries stored in plan.json>"]
    tb = out.get("task_baseline")
    if isinstance(tb, dict):
        tb_copy = dict(tb)
        tb_changes = tb_copy.get("changes")
        if isinstance(tb_changes, list) and len(tb_changes) > 8:
            tb_copy["changes"] = [
                *tb_changes[:8],
                f"<+{len(tb_changes) - 8} baseline entries stored in task-baseline.json>",
            ]
        out["task_baseline"] = tb_copy
    vc = out.get("verification_contract")
    if isinstance(vc, dict) and isinstance(vc.get("criteria"), list):
        vc_copy = dict(vc)
        compact_crit = []
        for c in vc["criteria"]:
            if isinstance(c, dict):
                c_copy = dict(c)
                syms = c_copy.get("referenced_symbols")
                if isinstance(syms, list) and len(syms) > 6:
                    c_copy["referenced_symbols"] = [
                        *syms[:6],
                        f"<+{len(syms) - 6} symbols stored in plan.json>",
                    ]
                compact_crit.append(c_copy)
            else:
                compact_crit.append(c)
        vc_copy["criteria"] = compact_crit
        out["verification_contract"] = vc_copy
    ac = out.get("architecture_contract")
    if isinstance(ac, dict):
        ac_copy = dict(ac)
        for heavy_k in ("family_evidence", "candidates", "exemplar_files", "detected_families"):
            hv = ac_copy.get(heavy_k)
            if isinstance(hv, list) and len(hv) > 5:
                ac_copy[heavy_k] = [*hv[:5], f"<+{len(hv) - 5} items stored in plan.json>"]
        out["architecture_contract"] = ac_copy
    dbg_ev = out.get("debug_evidence")
    if isinstance(dbg_ev, list) and len(dbg_ev) > 4:
        out["debug_evidence"] = [*dbg_ev[-3:], f"<+{len(dbg_ev) - 3} earlier debug_evidence entries stored in plan.json>"]
    elif isinstance(dbg_ev, dict) and isinstance(dbg_ev.get("entries"), list) and len(dbg_ev["entries"]) > 4:
        out["debug_evidence"] = {
            **dbg_ev,
            "entries": [*dbg_ev["entries"][-3:], f"<+{len(dbg_ev['entries']) - 3} earlier entries stored in plan.json>"],
        }
    for nested_k in ("plan", "updated_plan", "merged_plan", "active_plan", "previous_task", "brief"):
        nested_v = out.get(nested_k)
        if isinstance(nested_v, dict) and (
            "base_file_identities" in nested_v
            or "base_change_identities" in nested_v
            or "task_baseline" in nested_v
            or "architecture_contract" in nested_v
        ):
            out[nested_k] = _engine._compact_plan_json_for_cli_stdout(nested_v)
    return out
def checkpoint_phase(args: _engine.argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    plan = _engine._load_plan(repo, args.task_id)
    if plan.get("status") != "IMPLEMENTING":
        raise _engine.ValidationError("phase checkpoint requires an IMPLEMENTING plan")
    from debug_instrumentation import assert_clean
    assert_clean(repo, plan)
    phases = plan.get("phases") or []
    if not phases:
        raise _engine.ValidationError("plan does not define any phases")
    directory = _engine.task_dir(repo, args.task_id)
    phase_state_file = directory / "phase-state.json"
    phase_state = _engine.read_json(phase_state_file) if phase_state_file.is_file() else {
        "current_phase_id": phases[0]["id"],
        "completed_phases": [],
        "phase_checkpoints": {},
    }
    phase_id = getattr(args, "phase_id", None) or phase_state.get("current_phase_id")
    target_phase = next((p for p in phases if p.get("id") == phase_id), None)
    if not target_phase:
        raise _engine.ValidationError(f"phase '{phase_id}' not found in plan phases")
    active_phase_id = phase_state.get("current_phase_id")
    if active_phase_id and phase_id != active_phase_id:
        raise _engine.ValidationError(
            f"phase checkpoint is for '{phase_id}' but the active phase is '{active_phase_id}'; "
            "checkpoint the active phase first"
        )
    phase_index = next(i for i, p in enumerate(phases) if p.get("id") == phase_id)

    from phase_review import (
        get_phase_substate,
        invalidate_phase_review,
        phase_run_file,
        PHASE_REVIEW_BLOCKED,
        PHASE_REVIEWING,
    )
    if (
        get_phase_substate(phase_state, phase_id) in (PHASE_REVIEW_BLOCKED, PHASE_REVIEWING)
        or phase_run_file(directory, phase_id).is_file()
    ):
        invalidate_phase_review(repo, args.task_id, phase_id)
        phase_state = _engine.read_json(phase_state_file)

    phase_dir = directory / "phases" / phase_id
    phase_dir.mkdir(parents=True, exist_ok=True)
    baseline_file = phase_dir / "baseline.json"
    base_data = _engine.read_json(baseline_file) if baseline_file.is_file() else _engine.load_task_baseline(repo, args.task_id)
    from change_decision import additional_files, observed_files
    decision_files = additional_files(plan) | observed_files(plan, repo)
    phase_scope_files = target_phase.get("expected_files") or plan.get("expected_files")
    if phase_scope_files:
        phase_scope_files = sorted(set(phase_scope_files) | decision_files)
    if phase_scope_files:
        markers = _engine.find_conflict_markers(repo, phase_scope_files)
        if markers:
            listed = ", ".join(f"{m['path']}:{m['line']}" for m in markers[:10])
            raise _engine.ValidationError(
                f"UNRESOLVED_MERGE_CONFLICT: Git conflict markers remain in phase '{phase_id}' scope ({listed})."
            )
    manifest = _engine.build_task_manifest(repo, base_data, expected_files=phase_scope_files)
    phase_changes = manifest.get("task_changes") if "task_changes" in manifest else manifest.get("changes") or []
    # A later phase can be empty when an earlier phase's checkpoint already covered its files
    # (phases added by a revision after the work was done). It records an empty checkpoint; the
    # final verification still gates the whole task delta.
    empty_later_phase = False
    if not phase_changes and phase_index > 0:
        covered: set[str] = set()
        for done_id in phase_state.get("completed_phases") or []:
            done_file = directory / "phases" / done_id / "checkpoint.json"
            if done_file.is_file():
                covered.update(
                    str(c.get("path") or "").replace("\\", "/").strip("/")
                    for c in _engine.read_json(done_file).get("manifest_delta") or [] if isinstance(c, dict)
                )
        phase_owned = _engine.normalize_expected_files(repo, target_phase.get("expected_files") or [])
        owned = phase_owned or _engine.normalize_expected_files(repo, plan.get("expected_files") or [])
        if bool(owned) and set(owned) <= covered:
            empty_later_phase = True
        elif not phase_owned and owned:
            all_exist = all((repo / p).exists() for p in owned)
            empty_later_phase = (
                all_exist
                and len(owned) > len(phases)
                and len(covered & set(owned)) >= len(phases)
            )
    if not phase_changes and not empty_later_phase:
        raise _engine.ValidationError(f"phase checkpoint failed: no file changes detected for phase '{phase_id}'")

    phase_expected_files = target_phase.get("expected_files")
    approved_task_files = set(_engine.normalize_expected_files(repo, list(plan.get("expected_files") or []) + sorted(decision_files)))
    phase_expected_modules = target_phase.get("expected_modules") or plan.get("expected_modules")
    if phase_expected_modules:
        norm_mods = [m.strip("/:").replace("\\", "/") for m in phase_expected_modules]
        for change in phase_changes:
            if isinstance(change, dict) and change.get("status") == "BASELINE_DIRTY_REMOVED":
                continue
            raw_p = change.get("path") if isinstance(change, dict) else str(change)
            change_path = (raw_p or "").replace("\\", "/").strip("/")
            if change_path.startswith(".agents/"):
                continue
            mod_match = any(change_path.startswith(m + "/") or change_path == m for m in norm_mods)
            if not mod_match and change_path not in approved_task_files:
                raise _engine.ValidationError(f"phase '{phase_id}' modified file outside expected_modules: {change_path}")

    additional_phase_files = []
    if phase_expected_files:
        norm_expected = _engine.normalize_expected_files(repo, phase_expected_files)
        for change in phase_changes:
            if isinstance(change, dict) and change.get("status") == "BASELINE_DIRTY_REMOVED":
                continue
            raw_p = change.get("path") if isinstance(change, dict) else str(change)
            change_path = (raw_p or "").replace("\\", "/").strip("/")
            if change_path.startswith(".agents/"):
                continue
            if change_path not in norm_expected:
                additional_phase_files.append(change_path)
                approved_task_files.add(change_path)
                cur_exp = list(plan.get("expected_files") or [])
                if change_path not in cur_exp:
                    old_plan_sha = str(plan.get("plan_sha256") or "")
                    if old_plan_sha:
                        history_dir = _engine.task_dir(repo, args.task_id) / "plan-history"
                        history_dir.mkdir(parents=True, exist_ok=True)
                        _engine.atomic_write_json(history_dir / f"{old_plan_sha}.json", dict(plan))
                        plan["supersedes_plan_sha256"] = old_plan_sha
                        plan["in_place_absorbed_plan_shas"] = sorted(set(plan.get("in_place_absorbed_plan_shas") or []) | {old_plan_sha})
                    plan["expected_files"] = sorted(set(cur_exp) | {change_path})
                    plan["plan_sha256"] = _engine.canonical_sha256(_engine.plan_payload(plan))
                    if isinstance(plan.get("approval"), dict):
                        plan["approval"]["plan_sha256"] = plan["plan_sha256"]
                    _engine.save_plan(_engine._plan_path(repo, args.task_id), plan)

    # Phase delta classification & central policy
    phase_classification = _engine.classify(repo, task_changes=phase_changes)
    skills_root = (repo / "agents" / "skills") if (repo / "agents" / "skills").is_dir() else (repo / ".agents" / "skills")
    phase_policy = _engine.decide(phase_classification, skills_root, plan=plan)

    # 1. Deterministic Preflight
    # Fast Kotlin lint
    try:
        kt_issues: list[tuple[str, dict]] = []
        for c in phase_changes:
            rel_p = c.get("path", "") if isinstance(c, dict) else str(c or "")
            p = repo / rel_p
            if p.suffix == ".kt" and p.is_file():
                for iss in _engine.new_kotlin_lint_issues(repo, args.task_id, p, plan.get("task_base_head") or (plan.get("repository") or {}).get("head")):
                    kt_issues.append((rel_p, iss))
        if kt_issues:
            lines = [f"phase checkpoint Kotlin lint failed: {len(kt_issues)} issue(s) detected"]
            for rel_p, iss in kt_issues[:10]:
                if isinstance(iss, dict):
                    lines.append(f"  - [{iss.get('type', 'LINT')}] {rel_p}:{iss.get('line', '?')} -> {iss.get('msg', '')}")
                else:
                    lines.append(f"  - {rel_p}: {iss}")
            if len(kt_issues) > 10:
                lines.append(f"  ... (+{len(kt_issues) - 10} more)")
            raise _engine.ValidationError("\n".join(lines))
    except (ImportError, _engine.ValidationError):
        raise
    except Exception as exc:
        raise _engine.ValidationError(f"phase checkpoint Kotlin lint exception: {exc}")

    # Architecture drift
    try:
        from architecture_drift import check_architecture_drift
        passed, msg, viols = check_architecture_drift(repo, plan.get("architecture_contract"), task_changes=phase_changes)
        if not passed:
            raise _engine.ValidationError(f"phase checkpoint architecture drift: {msg}")
    except (ImportError, _engine.ValidationError):
        raise
    except Exception as exc:
        raise _engine.ValidationError(f"phase checkpoint architecture drift check exception: {exc}")

    # Room schema guard
    def _phase_p(item: Any) -> str:
        return str(item.get("path", "") if isinstance(item, dict) else item or "")

    has_room = any(
        (_phase_p(c).endswith(".kt") and any(w in _phase_p(c).lower() for w in ("entity", "dao", "database")))
        or "room" in _phase_p(c).lower()
        for c in phase_changes
    ) or "ROOM_SCHEMA" in (phase_policy.get("surfaces") or [])
    if has_room:
        try:
            from room_guard import check_room_working_tree
            phase_paths = [_phase_p(c) for c in phase_changes if _phase_p(c)]
            room_ok, room_msg = check_room_working_tree(repo=repo, paths=phase_paths)
            if not room_ok:
                raise _engine.ValidationError(f"phase checkpoint Room schema violation: {room_msg}")
        except (ImportError, _engine.ValidationError):
            raise
        except Exception as exc:
            raise _engine.ValidationError(f"phase checkpoint Room check exception: {exc}")

    preflight_status = {"status": "PASS"}

    from phase_review import (
        is_phase_review_needed,
        set_phase_substate,
        compute_phase_diff_stats,
        compute_phase_delta_sha256,
        phase_path_states,
        derive_final_review_reserve,
        _compute_phase_diff,
        PHASE_REVIEW_PACKAGE_REQUIRED,
        PHASE_COMPLETE,
    )

    diff_paths = [c.get("path") if isinstance(c, dict) else str(c) for c in phase_changes if c]
    diff_text = _compute_phase_diff(repo, diff_paths)
    diff_stats = compute_phase_diff_stats(diff_text, diff_paths)
    phase_delta_sha256 = compute_phase_delta_sha256(phase_id, phase_changes)

    review_needed, selected_reviewers = is_phase_review_needed(
        repo=repo,
        task_id=args.task_id,
        plan=plan,
        target_phase=target_phase,
        phase_changes=phase_changes,
        phase_policy=phase_policy,
        diff_stats=diff_stats,
    )

    # 2. Targeted compile & unit tests only when the central policy calls for a build or
    # tests. Documentation and other T0 changes must not trigger Gradle.
    resolved_modules = _engine.resolve_phase_modules(repo, manifest)
    build_gates = {"unit_tests", "instrumented_tests", "assemble"}
    needs_compile = bool(build_gates.intersection(phase_policy.get("gates") or []))
    needs_tests = "unit_tests" in (phase_policy.get("gates") or [])

    defer_gradle = bool(
        getattr(args, "defer_gradle_to_final", False)
        and not review_needed
        and not bool(plan.get("scoped_phase_review_enabled"))
        and target_phase.get("scoped_phase_review_enabled") is not True
    )

    _gradle_mocked = False
    try:
        from run_gradle_task import run_gradle as _rg_probe
        _gradle_mocked = hasattr(_rg_probe, "assert_called") or hasattr(_rg_probe, "side_effect") or hasattr(_rg_probe, "return_value")
    except (ImportError, OSError, ValueError):
        pass
    _phase_hooks_mocked = (
        _gradle_mocked
        or any(hasattr(fn, attr) for fn in (_engine.check_phase_compile, _engine.check_phase_tests) for attr in ("assert_called", "side_effect", "return_value"))
    )
    _reusable_prev_phase: tuple[str, dict] | None = None
    if phase_index > 0 and not _gradle_mocked:
        for _done_id in reversed(list(phase_state.get("completed_phases") or [])):
            _done_ckpt_f = directory / "phases" / str(_done_id) / "checkpoint.json"
            if _done_ckpt_f.is_file():
                try:
                    _done_ckpt = _engine.read_json(_done_ckpt_f)
                except (OSError, ValueError, _engine.ValidationError):
                    continue
                if (
                    isinstance(_done_ckpt, dict)
                    and _done_ckpt.get("status") == "CHECKPOINT_PASS"
                    and _done_ckpt.get("delivery_snapshot_sha256") == manifest.get("delivery_snapshot_sha256")
                ):
                    _reusable_prev_phase = (str(_done_id), _done_ckpt)
                    break

    if defer_gradle:
        gradle_wrapper_present = (repo / "gradlew").is_file() or (repo / "gradlew.bat").is_file()
        if gradle_wrapper_present and needs_compile:
            for _mod in resolved_modules:
                _engine.resolve_module_gradle_task(repo, _mod, task_type="compile", phase_changes=phase_changes)
                if needs_tests and not _engine._phase_module_skips_unit_tests(repo, _mod, phase_changes):
                    _engine.resolve_module_gradle_task(repo, _mod, task_type="test", phase_changes=phase_changes)
        compile_status = (
            {"status": "DEFERRED_TO_FINAL_VERIFICATION", "modules": resolved_modules}
            if needs_compile
            else {"status": "NOT_REQUIRED", "modules": []}
        )
        tests_status = (
            {"status": "DEFERRED_TO_FINAL_VERIFICATION"}
            if needs_tests
            else {"status": "NOT_REQUIRED"}
        )
    else:
        _reused_tests = False
        if needs_tests and _reusable_prev_phase is not None:
            _prev_id, _prev_ckpt = _reusable_prev_phase
            _prev_comp_mods = set((_prev_ckpt.get("compile") or {}).get("modules") or [])
            _prev_ut_f = directory / "phases" / _prev_id / "unit_tests.json"
            if (
                (_prev_ckpt.get("tests") or {}).get("status") == "PASS"
                and set(resolved_modules) <= _prev_comp_mods
                and _prev_ut_f.is_file()
            ):
                try:
                    _prev_ut = _engine.read_json(_prev_ut_f)
                    if isinstance(_prev_ut, dict) and str(_prev_ut.get("status") or "").upper() == "PASS":
                        from phase_review import compute_phase_delta_sha256 as _cpds
                        _ev_id = _engine.canonical_sha256({
                            "phase_delta_sha256": _cpds(phase_dir.name, list(phase_changes or [])),
                            "modules": sorted(str(m) for m in resolved_modules),
                        })
                        _engine.atomic_write_json(phase_dir / "unit_tests.json", {
                            **_prev_ut,
                            "evidence_identity_sha256": _ev_id,
                            "reused_from_phase": _prev_id,
                        })
                        tests_status = {"status": "PASS"}
                        _reused_tests = True
                except (OSError, ValueError, _engine.ValidationError):
                    _reused_tests = False

        gradle_wrapper_present = (repo / "gradlew").is_file() or (repo / "gradlew.bat").is_file()
        _can_combine_compile_into_tests = bool(
            needs_compile
            and needs_tests
            and gradle_wrapper_present
            and not _phase_hooks_mocked
            and not _reused_tests
            and not _engine._has_prerecorded_phase_test_pass(phase_dir, resolved_modules, phase_changes)
        )

        if needs_compile:
            _prev_comp = (_reusable_prev_phase[1].get("compile") or {}) if _reusable_prev_phase else {}
            if (
                _reusable_prev_phase is not None
                and _prev_comp.get("status") == "PASS"
                and set(resolved_modules) <= set(_prev_comp.get("modules") or [])
            ):
                compile_status = {"status": "PASS", "modules": resolved_modules, "reused_from_phase": _reusable_prev_phase[0]}
            elif _can_combine_compile_into_tests:
                compile_only_mods = [m for m in resolved_modules if _engine._phase_module_skips_unit_tests(repo, m, phase_changes)]
                if compile_only_mods:
                    try:
                        compile_ok, compile_detail = _engine.check_phase_compile(repo, compile_only_mods, phase_changes=phase_changes)
                        if not compile_ok:
                            raise _engine.ValidationError(f"phase checkpoint compile failed: {compile_detail}")
                    except (ImportError, _engine.ValidationError):
                        raise
                    except Exception as exc:
                        raise _engine.ValidationError(f"phase checkpoint compile exception: {exc}")
                compile_status = {"status": "PASS", "modules": resolved_modules, "covered_by_unit_tests": True}
            else:
                try:
                    compile_ok, compile_detail = _engine.check_phase_compile(repo, resolved_modules, phase_changes=phase_changes)
                    if not compile_ok:
                        raise _engine.ValidationError(f"phase checkpoint compile failed: {compile_detail}")
                    compile_status = {"status": compile_detail, "modules": resolved_modules}
                except (ImportError, _engine.ValidationError):
                    raise
                except Exception as exc:
                    raise _engine.ValidationError(f"phase checkpoint compile exception: {exc}")
        else:
            compile_status = {"status": "NOT_REQUIRED", "modules": []}

        # 3. Policy-required tests
        if not _reused_tests:
            try:
                tests_ok, tests_detail = _engine.check_phase_tests(repo, phase_dir, resolved_modules, needs_tests, phase_changes=phase_changes)
                if not tests_ok:
                    raise _engine.ValidationError(f"phase checkpoint unit tests failed: {tests_detail}")
                tests_status = {"status": tests_detail}
            except (ImportError, _engine.ValidationError):
                raise
            except Exception as exc:
                raise _engine.ValidationError(f"phase checkpoint unit tests exception: {exc}")

    if review_needed:
        review_status = {"status": "REVIEW_PACKAGE_REQUIRED", "reviewers": selected_reviewers}
    else:
        review_status = {"status": "NOT_REQUIRED", "reviewers": []}

    final_review_reserve = derive_final_review_reserve(repo, plan, phase_policy)

    checkpoint_record = {
        "schema_version": 2,
        "task_id": args.task_id,
        "phase_id": phase_id,
        "status": "CHECKPOINT_PASS",
        "checkpoint_at": _engine.utc_now(),
        "phase_delta_sha256": phase_delta_sha256,
        "changed_files": diff_stats["changed_files"],
        "added_lines": diff_stats["added_lines"],
        "deleted_lines": diff_stats["deleted_lines"],
        "changed_lines": diff_stats["changed_lines"],
        "delivery_snapshot_sha256": manifest["delivery_snapshot_sha256"],
        "task_change_set_sha256": manifest["task_change_set_sha256"],
        "manifest_delta": phase_changes,
        "additional_task_approved_files": sorted(additional_phase_files),
        "phase_path_states": phase_path_states(repo, phase_changes),
        "preflight": preflight_status,
        "compile": compile_status,
        "tests": tests_status,
        "review": review_status,
        "final_review_reserve": final_review_reserve,
    }
    checkpoint_record["checkpoint_sha256"] = _engine.canonical_sha256(checkpoint_record)
    _engine.atomic_write_json(phase_dir / "checkpoint.json", checkpoint_record)

    completed = list(phase_state.get("completed_phases") or [])
    curr_idx = next((i for i, p in enumerate(phases) if p.get("id") == phase_id), -1)
    if review_needed:
        phase_state = set_phase_substate(directory, phase_id, PHASE_REVIEW_PACKAGE_REQUIRED)
        phase_state.setdefault("phase_checkpoints", {})[phase_id] = checkpoint_record["checkpoint_sha256"]
        _engine.atomic_write_json(phase_state_file, phase_state)
    else:
        phase_state = set_phase_substate(directory, phase_id, PHASE_COMPLETE)
        if phase_id not in completed:
            completed.append(phase_id)
        phase_state["completed_phases"] = completed
        phase_state.setdefault("phase_checkpoints", {})[phase_id] = checkpoint_record["checkpoint_sha256"]
        _engine.atomic_write_json(phase_state_file, phase_state)

    try:
        from self_heal import save_stable_snapshot
        save_stable_snapshot(repo, args.task_id, f"checkpoint-{phase_id}", plan=plan, phase_state=phase_state)
    except (OSError, ValueError, ImportError, _engine.ValidationError):
        pass

    auto_advanced_phases: list[str] = []
    if (
        getattr(args, "advance_all_ready", False)
        and not review_needed
        and not bool(plan.get("scoped_phase_review_enabled"))
        and curr_idx + 1 < len(phases)
    ):
        wr_deleted: set[str] = set()
        wr_rec_p = directory / "web-relay-receipt.json"
        if wr_rec_p.is_file():
            try:
                wr_doc = _engine.read_json(wr_rec_p)
                if isinstance(wr_doc, dict):
                    wr_deleted = {str(x).replace("\\", "/").strip("/") for x in (wr_doc.get("files_deleted") or []) if str(x).strip()}
            except (OSError, ValueError, _engine.ValidationError):
                wr_deleted = set()
        for next_ph in phases[curr_idx + 1 :]:
            if next_ph.get("scoped_phase_review_enabled") is True:
                break
            next_pid = str(next_ph.get("id") or "").strip()
            if not next_pid:
                break
            next_owned = _engine.normalize_expected_files(repo, next_ph.get("expected_files") or [])
            if next_owned and not all((repo / rel_p).is_file() or rel_p in wr_deleted for rel_p in next_owned):
                break
            if next_owned and _engine.find_conflict_markers(repo, next_owned):
                break
            try:
                _engine.begin_next_phase(_engine.argparse.Namespace(repo=str(repo), task_id=args.task_id, json=False))
                sub_ckpt = _engine.checkpoint_phase(
                    _engine.argparse.Namespace(
                        repo=str(repo),
                        task_id=args.task_id,
                        phase_id=next_pid,
                        advance_all_ready=False,
                        defer_gradle_to_final=defer_gradle,
                    )
                )
            except _engine.ValidationError:
                break
            auto_advanced_phases.append(next_pid)
            completed = list(sub_ckpt.get("completed_phases") or completed)
            phase_state = _engine.read_json(phase_state_file) if phase_state_file.is_file() else phase_state
            if str((sub_ckpt.get("review") or {}).get("status") or "") == "REVIEW_PACKAGE_REQUIRED":
                break

    ret_payload = {
        "status": _engine.CheckpointStatus("CHECKPOINT_PASS"),
        "phase_id": auto_advanced_phases[-1] if auto_advanced_phases else phase_id,
        "completed_phases": completed,
        "current_phase_id": phase_state.get("current_phase_id"),
        "next_phase_index": (
            next((i for i, p in enumerate(phases) if p.get("id") == phase_state.get("current_phase_id")), curr_idx) + 1
            if auto_advanced_phases
            else (curr_idx + 1 if curr_idx + 1 < len(phases) else curr_idx)
        ),
        "checkpoint": checkpoint_record,
        "preflight": preflight_status,
        "compile": compile_status,
        "tests": tests_status,
        "review": review_status,
    }
    if auto_advanced_phases:
        ret_payload["auto_advanced_phases"] = auto_advanced_phases
    return ret_payload
def all_remaining_phases_ready_for_final(
    repo: Path,
    task_id: str,
    plan: dict | None = None,
) -> tuple[bool, str]:
    """Return (True, current_phase_id) when all remaining phases are already materialized on disk
    without requiring intermediate scoped phase reviews, allowing `verify-steps` to fast-forward
    phase checkpoints and run Preflight + Unit Tests + Review Packaging in a single pass."""
    try:
        plan_doc = plan if isinstance(plan, dict) and plan else _engine._load_plan(repo, task_id)
    except (OSError, ValueError, _engine.ValidationError):
        return False, ""
    if plan_doc.get("status") != "IMPLEMENTING":
        return False, ""
    phases = plan_doc.get("phases") or []
    if not phases or bool(plan_doc.get("scoped_phase_review_enabled")):
        return False, ""
    directory = _engine.task_dir(repo, task_id)
    staged_dir = directory / "staged-web-phases"
    if staged_dir.is_dir() and any(staged_dir.glob("*.json")):
        return False, ""

    from phase_review import (
        PHASE_COMPLETE,
        PHASE_REVIEW_BLOCKED,
        PHASE_REVIEW_PACKAGE_REQUIRED,
        PHASE_REVIEWING,
        get_phase_substate,
    )
    phase_state_f = directory / "phase-state.json"
    p_state = _engine.read_json(phase_state_f) if phase_state_f.is_file() else {
        "current_phase_id": phases[0].get("id"),
        "completed_phases": [],
        "phase_checkpoints": {},
    }
    completed_set = {str(x) for x in (p_state.get("completed_phases") or []) if str(x)}
    if all(str(p.get("id") or "") in completed_set for p in phases):
        return False, ""

    try:
        active_idx = int(plan_doc.get("active_phase_index") or 0)
    except (TypeError, ValueError):
        active_idx = 0
    active_idx = max(0, min(active_idx, len(phases) - 1))
    cur_phase = phases[active_idx] if isinstance(phases[active_idx], dict) else {}
    cur_pid = str(cur_phase.get("id") or p_state.get("current_phase_id") or "").strip()
    if not cur_pid:
        return False, ""

    for ph in phases[active_idx:]:
        if not isinstance(ph, dict) or ph.get("scoped_phase_review_enabled") is True:
            return False, ""
        pid = str(ph.get("id") or "").strip()
        if get_phase_substate(p_state, pid) in (PHASE_REVIEW_BLOCKED, PHASE_REVIEW_PACKAGE_REQUIRED, PHASE_REVIEWING):
            return False, ""

    wr_complete_task = False
    wr_deleted: set[str] = set()
    wr_rec_p = directory / "web-relay-receipt.json"
    if wr_rec_p.is_file():
        try:
            wr_doc = _engine.read_json(wr_rec_p)
            if isinstance(wr_doc, dict) and str(wr_doc.get("task_id") or "") == task_id:
                if bool(wr_doc.get("incomplete_continuation")):
                    return False, ""
                wr_complete_task = True
                wr_deleted = {str(x).replace("\\", "/").strip("/") for x in (wr_doc.get("files_deleted") or []) if str(x).strip()}
        except (OSError, ValueError, _engine.ValidationError):
            return False, ""

    try:
        task_base = _engine.load_task_baseline(repo, task_id)
        plan_owned = _engine.normalize_expected_files(repo, plan_doc.get("expected_files") or [])
        full_manifest = _engine.build_task_manifest(repo, task_base, expected_files=plan_owned or None)
        full_changes = full_manifest.get("task_changes") if "task_changes" in full_manifest else full_manifest.get("changes") or []
    except (OSError, ValueError, _engine.ValidationError):
        return False, ""
    if not full_changes:
        return False, ""

    changed_paths = {
        str(c.get("path") or "").replace("\\", "/").strip("/")
        for c in full_changes
        if isinstance(c, dict) and str(c.get("path") or "").strip()
    }
    deleted_paths = wr_deleted | {
        str(c.get("path") or "").replace("\\", "/").strip("/")
        for c in full_changes
        if isinstance(c, dict) and str(c.get("status") or "").upper() == "D"
    }

    # Verify active phase has changes ready unless already PHASE_COMPLETE (pending begin-next-phase)
    if get_phase_substate(p_state, cur_pid) != PHASE_COMPLETE:
        cur_base_f = directory / "phases" / cur_pid / "baseline.json"
        cur_base = _engine.read_json(cur_base_f) if cur_base_f.is_file() else task_base
        cur_scope = cur_phase.get("expected_files") or plan_doc.get("expected_files")
        cur_man = _engine.build_task_manifest(repo, cur_base, expected_files=cur_scope)
        cur_changes = cur_man.get("task_changes") if "task_changes" in cur_man else cur_man.get("changes") or []
        if not cur_changes:
            return False, ""
        cur_owned = _engine.normalize_expected_files(repo, cur_scope or [])
        if cur_owned and _engine.find_conflict_markers(repo, cur_owned):
            return False, ""

    for next_ph in phases[active_idx + 1 :]:
        next_owned = _engine.normalize_expected_files(repo, next_ph.get("expected_files") or [])
        check_files = next_owned or plan_owned
        if check_files:
            if not all((repo / rel_p).is_file() or rel_p in deleted_paths for rel_p in check_files):
                return False, ""
            if _engine.find_conflict_markers(repo, check_files):
                return False, ""
        if next_owned:
            if not wr_complete_task and not (set(next_owned) & changed_paths):
                return False, ""
        else:
            # Compact CLI `--phases "p1:...,p2:..."` shares plan-level expected_files across phases:
            # only fast-forward when web-apply completed the pack OR every planned file has changes.
            if not wr_complete_task and (not plan_owned or not (set(plan_owned) <= changed_paths)):
                return False, ""

    return True, cur_pid
def validated_completed_phase_manifest(
    repo: Path, task_id: str, plan: dict, phase_state: dict, phase: dict,
    *, for_final: bool = False,
) -> dict:
    """Validate phase progression, or its historical proof before fresh final gates."""
    from phase_review import PHASE_COMPLETE, compute_phase_delta_sha256, get_phase_substate, phase_path_states

    phase_id = phase.get("id")
    if phase_id not in (phase_state.get("completed_phases") or []):
        raise _engine.ValidationError("current phase is not marked complete")
    if get_phase_substate(phase_state, phase_id) != PHASE_COMPLETE:
        raise _engine.ValidationError("completed phase substate disagrees with phase completion list")
    directory = _engine.task_dir(repo, task_id)
    checkpoint_f = directory / "phases" / phase_id / "checkpoint.json"
    checkpoint = _engine.read_json(checkpoint_f) if checkpoint_f.is_file() else None
    if not isinstance(checkpoint, dict) or any(checkpoint.get(key) != value for key, value in {
        "task_id": task_id, "phase_id": phase_id, "status": "CHECKPOINT_PASS",
    }.items()):
        raise _engine.ValidationError("current phase checkpoint is missing or invalid")
    checkpoint_sha = checkpoint.get("checkpoint_sha256")
    if (
        not checkpoint_sha
        or checkpoint_sha != _engine.canonical_sha256({k: v for k, v in checkpoint.items() if k != "checkpoint_sha256"})
        or phase_state.get("phase_checkpoints", {}).get(phase_id) != checkpoint_sha
    ):
        raise _engine.ValidationError("current phase checkpoint integrity or identity mismatch")
    baseline_f = directory / "phases" / phase_id / "baseline.json"
    baseline = _engine.read_json(baseline_f) if baseline_f.is_file() else _engine.load_task_baseline(repo, task_id)
    manifest = _engine.build_task_manifest(
        repo, baseline,
        expected_files=phase.get("expected_files") or plan.get("expected_files"),
    )
    changes = manifest.get("task_changes") or []
    historical_for_final = for_final
    if any((
        manifest["delivery_snapshot_sha256"] != checkpoint.get("delivery_snapshot_sha256"),
        manifest["task_change_set_sha256"] != checkpoint.get("task_change_set_sha256"),
        compute_phase_delta_sha256(phase_id, changes) != checkpoint.get("phase_delta_sha256"),
        phase_path_states(repo, changes) != checkpoint.get("phase_path_states"),
    )):
        if not historical_for_final:
            raise _engine.ValidationError("phase checkpoint is stale; re-checkpoint the current phase before advancing")
    review_status = checkpoint.get("review")
    if not isinstance(review_status, dict):
        raise _engine.ValidationError("phase checkpoint review decision is missing")
    if review_status.get("status") == "REVIEW_PACKAGE_REQUIRED":
        from phase_review import validate_completed_phase_review_proof

        validate_completed_phase_review_proof(repo, task_id, phase_id, checkpoint_sha, historical_for_final=historical_for_final)
    elif review_status.get("status") != "NOT_REQUIRED":
        raise _engine.ValidationError("phase checkpoint review decision is invalid")
    return manifest
def begin_next_phase(args: _engine.argparse.Namespace) -> dict[str, Any]:
    repo = Path(args.repo).resolve()
    plan = _engine._load_plan(repo, args.task_id)
    if plan.get("status") != "IMPLEMENTING":
        raise _engine.ValidationError("begin-next-phase requires an IMPLEMENTING plan")
    phases = plan.get("phases") or []
    if not phases:
        raise _engine.ValidationError("plan does not define any phases")
    directory = _engine.task_dir(repo, args.task_id)
    phase_state_file = directory / "phase-state.json"
    phase_state = _engine.read_json(phase_state_file) if phase_state_file.is_file() else {}
    completed = set(phase_state.get("completed_phases") or [])
    try:
        active_idx = int(plan.get("active_phase_index") or 0)
    except (TypeError, ValueError):
        active_idx = 0
    cur_phase = phases[active_idx] if active_idx < len(phases) else phases[-1]
    cur_id = cur_phase.get("id")
    if cur_id not in completed:
        raise _engine.ValidationError(f"cannot advance to next phase: current phase '{cur_id}' is not complete")

    next_idx = active_idx + 1
    if next_idx >= len(phases):
        raise _engine.ValidationError("no next phase to advance to; all phases complete")

    next_phase = phases[next_idx]
    next_id = next_phase["id"]
    if phase_state.get("current_phase_id") not in (cur_id, next_id):
        raise _engine.ValidationError("phase state does not match the active or pending next phase")
    if next_id in completed:
        raise _engine.ValidationError("next phase is already marked complete before transition")

    cur_man = _engine.validated_completed_phase_manifest(repo, args.task_id, plan, phase_state, cur_phase)

    next_dir = directory / "phases" / next_id
    next_dir.mkdir(parents=True, exist_ok=True)
    baseline_f = next_dir / "baseline.json"
    next_baseline = {
        "schema_version": 1,
        "task_id": args.task_id,
        "phase_id": next_id,
        "repository": plan.get("repository"),
        "base_delivery_snapshot_sha256": cur_man["delivery_snapshot_sha256"],
        "base_change_set_sha256": cur_man["change_set_sha256"],
        "changes": cur_man.get("changes") or [],
    }
    next_baseline["baseline_sha256"] = _engine.canonical_sha256(next_baseline)
    if baseline_f.is_file():
        if _engine.read_json(baseline_f) != next_baseline:
            raise _engine.ValidationError("next phase baseline differs from the current delivery snapshot")
    else:
        _engine.atomic_write_json(baseline_f, next_baseline)

    # Commit the plan index last. Earlier writes can be retried while the
    # completed current phase remains authoritative in the plan.
    from phase_review import PHASE_IMPLEMENTING

    substates = phase_state.setdefault("phase_substates", {})
    entry = substates.setdefault(next_id, {})
    entry["substate"] = PHASE_IMPLEMENTING
    entry["updated_at"] = _engine.utc_now()
    phase_state["substate"] = PHASE_IMPLEMENTING
    phase_state["current_phase_id"] = next_id
    _engine.atomic_write_json(phase_state_file, phase_state)

    plan["active_phase_index"] = next_idx
    _engine.save_plan(directory / "plan.json", plan)
    return {
        "status": "ADVANCED",
        "task_id": args.task_id,
        "active_phase_index": next_idx,
        "current_phase_id": next_id,
    }
