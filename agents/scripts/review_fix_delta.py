"""Files changed since a reviewed run, and the reviewers those files alone route.

`prepare-verification` uses it to narrow a later review round, and the final verifier recomputes it
from the same saved manifests, so a stored policy is never trusted on its own word.
"""
from __future__ import annotations

from pathlib import Path


def _identities(manifest):
    from delivery_equivalence import _file_identities
    return _file_identities(manifest)


def _matches(text, identity, algorithm):
    import hashlib
    raw = text.encode("utf-8")
    for data in (raw, raw.replace(b"\r\n", b"\n")):
        digest = hashlib.new(algorithm, b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        if identity == "git:" + digest:
            return True
    return False


def _input_path(repo, task_id, run_id):
    from _vnext_common import state_root, validate_id
    return state_root(repo).parent / "cache/review-inputs" / validate_id(task_id) / (validate_id(run_id) + ".json")


def capture_review_inputs(repo, task_directory, run_id, manifest, plan):
    """Optional private cache, verified against frozen Git blob identities on use.

    Missing, filtered, secret-bearing, binary or oversized text falls back to
    conservative file routing. No Git objects/history or review proof is written.
    """
    from _vnext_common import atomic_write_json, read_json, redact_text, ValidationError
    from delivery_manifest import SECRET_PATH_MARKERS
    identities, files, total = _identities(manifest), {}, 0
    for relative in sorted(_entries(manifest)):
        item = identities.get(relative) or {}
        path = repo / relative
        if (any(marker in relative.lower() for marker in SECRET_PATH_MARKERS)
                or item.get("git_mode") not in {"100644", "100755"} or path.is_symlink()
                or not path.resolve().is_relative_to(repo.resolve()) or not path.is_file()
                or path.stat().st_size > 1024 * 1024 or total > 16 * 1024 * 1024):
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeError:
            continue
        if "\0" in text or redact_text(text) != text or not _matches(text, item.get("content_identity"), manifest.get("object_format", "sha1")):
            continue
        files[relative] = text
        total += len(text.encode("utf-8"))
    record = {"schema_version": 1, "task_id": plan["task_id"], "run_id": run_id,
              "plan_sha256": plan["plan_sha256"], "repository": manifest.get("repository"),
              "delivery_snapshot_sha256": manifest["delivery_snapshot_sha256"],
              "change_set_sha256": manifest["change_set_sha256"], "files": files}
    destination = _input_path(repo, plan["task_id"], run_id)
    if destination.resolve() != destination.absolute() or not destination.resolve().is_relative_to(repo.resolve()):
        raise ValidationError("review input cache escapes managed cache")
    if destination.exists():
        if read_json(destination) != record:
            raise ValidationError("review input cache is immutable")
    else:
        atomic_write_json(destination, record)


def _comparison_texts(repo, previous, current, plan, previous_run_id, files):
    from _vnext_common import read_json, ValidationError
    path = _input_path(repo, plan["task_id"], previous_run_id)
    if not path.exists():
        return None
    if path.resolve() != path.absolute() or not path.resolve().is_relative_to(repo.resolve()) or path.stat().st_size > 32 * 1024 * 1024:
        raise ValidationError("invalid review input cache")
    record = read_json(path)
    expected = {"schema_version": 1, "task_id": plan["task_id"], "run_id": previous_run_id,
                "plan_sha256": plan["plan_sha256"], "repository": previous.get("repository"),
                "delivery_snapshot_sha256": previous["delivery_snapshot_sha256"],
                "change_set_sha256": previous["change_set_sha256"]}
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValidationError("review input cache binding mismatch")
    before, after, comparison = _identities(previous), _identities(current), {}
    for relative in files:
        old, new = before.get(relative), after.get(relative)
        if old and old.get("git_mode") not in {"100644", "100755"} or new and new.get("git_mode") not in {"100644", "100755"}:
            return None
        if old and new and old.get("git_mode") != new.get("git_mode"):
            return None
        old_text = record.get("files", {}).get(relative) if old else ""
        if old_text is None or old and not _matches(old_text, old.get("content_identity"), previous.get("object_format", "sha1")):
            return None
        source = repo / relative
        if new:
            if source.is_symlink() or not source.resolve().is_relative_to(repo.resolve()) or source.stat().st_size > 1024 * 1024:
                return None
            new_text = source.read_bytes().decode("utf-8")
            if not _matches(new_text, new.get("content_identity"), current.get("object_format", "sha1")):
                return None
        else:
            new_text = ""
        comparison[relative] = (old_text, new_text)
    return comparison


def build_fix_diff(repo, task_directory, manifest, plan, policy):
    """A bounded-context follow-up package; full task identities remain unchanged."""
    import difflib
    from _vnext_common import read_json, ValidationError, validate_id
    delta = policy.get("fix_delta") or {}
    if delta.get("comparison") != "REVIEWED_TEXT":
        return None
    source_run = validate_id((policy.get("later_round_source") or {}).get("run_id", ""))
    previous = read_json(task_directory / ("manifest-" + source_run + ".json"))
    comparison = _comparison_texts(repo, previous, manifest, plan, source_run, delta.get("files") or [])
    if comparison is None:
        raise ValidationError("Reviewed text is unavailable; prepare a fresh follow-up review policy before dispatch")
    return "\n".join("".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                       fromfile="a/" + relative, tofile="b/" + relative, n=10))
                       for relative, (old, new) in sorted(comparison.items()))


def _entries(manifest: dict) -> dict[str, tuple]:
    changes = manifest.get("task_changes") if "task_changes" in manifest else manifest.get("changes")
    return {
        str(item.get("path")): (item.get("content_identity"), item.get("git_mode"), item.get("worktree_git_mode"), item.get("old_path"))
        for item in changes or [] if isinstance(item, dict) and item.get("path")
    }


def compute_fix_delta(
    repo: Path,
    task_directory: Path,
    previous_run_id: str,
    current_manifest: dict,
    plan: dict,
    skills_root: Path,
    project_kind: str,
) -> dict | None:
    """{"files": [...], "reviewers": [...]}, or None when the delta cannot be judged (everyone reruns)."""
    try:
        from _vnext_common import read_json, validate_id, state_root
        from evidence_store import EvidenceStore
        from change_classifier import classify
        from review_policy import decide

        validate_id(previous_run_id, "run_id")
        previous = read_json(Path(task_directory) / f"manifest-{previous_run_id}.json")
        reviewed = EvidenceStore(state_root(repo)).read(previous["delivery_snapshot_sha256"], previous_run_id, "reviews")
        if reviewed.get("change_set_sha256") != previous.get("change_set_sha256"):
            return None
        before, after = _identities(previous), _identities(current_manifest)
        files = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
        if not files:
            return {"files": [], "reviewers": []}
        from change_decision import accepted_files
        accepted = accepted_files(plan, previous_run_id, previous, current_manifest) & set(files)
        files = sorted(set(files) - accepted)
        decision_basis = {"developer_accepted_files": sorted(accepted)} if accepted else {}
        if not files:
            return {"files": [], "reviewers": [], **decision_basis}
        comparison = _comparison_texts(repo, previous, current_manifest, plan, previous_run_id, files)
        present = [{"path": path} for path in files if path in after or comparison is not None]
        if not present:
            # Only deletions since the review: the regression reviewer covers what they break.
            return {"files": files, "reviewers": ["regression-impact-reviewer-agent"], **decision_basis}
        delta_class = classify(repo, task_changes=present, candidate_paths=[item["path"] for item in present],
                               progress=False, review_comparison=comparison)
        if not delta_class.get("surfaces"):
            return None
        # The delta's own classification (surfaces, size, severity), never mixed with the whole change's.
        routed = decide(delta_class, skills_root, project_kind=project_kind,
                        task_kind=str(plan.get("task_kind") or "FEATURE"), plan=plan, review_scope="FIX_DELTA")
        reviewers = set(routed.get("reviewers") or [])
        if any(path not in after for path in files):
            reviewers.add("regression-impact-reviewer-agent")
        return {"files": files, "reviewers": sorted(reviewers),
                **decision_basis,
                "comparison": "REVIEWED_TEXT" if comparison is not None else "FILE_SCOPE_FALLBACK"}
    except Exception:
        return None
