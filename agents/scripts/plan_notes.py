"""Non-authoritative, task/plan-bound clarifications; never edit approval payloads."""
from pathlib import Path

from _vnext_common import ValidationError, canonical_sha256, read_json, utc_now


def register_parser(sub, common):
    parser = sub.add_parser("plan-note", parents=[common])
    parser.add_argument("--text", required=True)
    parser.add_argument("--source", choices=("conversation", "developer_terminal", "approved-plan"), required=True)
    parser.add_argument("--proof-reference", required=True)
    parser.set_defaults(handler=record_note)


def note_section(directory, plan):
    lines = []
    for path in sorted((directory / "plan-notes").glob("*.json")):
        row = read_json(path)
        if (not isinstance(row, dict) or row.get("schema_version") != 1 or row.get("task_id") != plan["task_id"]
                or row.get("source") not in {"conversation", "developer_terminal", "approved-plan"}
                or not isinstance(row.get("text"), str) or not row["text"].strip()
                or not isinstance(row.get("proof_reference"), str) or not row["proof_reference"].strip()
                or row.get("receipt_sha256") != canonical_sha256({k: v for k, v in row.items() if k != "receipt_sha256"})):
            raise ValidationError("invalid plan clarification receipt")
        if row.get("plan_sha256") == plan.get("plan_sha256"):
            from _vnext_common import redact_text
            lines.append(f"- {redact_text(row['text'])} (source: {row['source']}; decision: {redact_text(row['proof_reference'])})")
    if not lines:
        return ""
    return "\n\n## Clarifications (no additional authority)\n\n" + (
        "These notes explain existing decisions. They do not replace the approved requirements, "
        "grant scope, waive checks, accept edits or certify reviewer PASS.\n\n"
    ) + "\n".join(lines) + "\n"


def record_note(args):
    from _workflow import engine
    from evidence_store import StateLock
    from plan_authority import validate_plan_hash
    repo = Path(args.repo).resolve()
    with StateLock(engine.state_root(repo)):
        engine.assert_single_live_task(repo, allowed_task_id=args.task_id)
        plan = engine._load_plan(repo, args.task_id)
        if (plan.get("status") not in {"IMPLEMENTING", "VERIFYING", "BLOCKED", "READY_FOR_DELIVERY"}
                or not validate_plan_hash(plan)[0] or not plan.get("approval")
                or plan.get("execution_nonce") != plan["approval"].get("single_use_nonce")):
            raise ValidationError("plan-note requires a valid approved live task")
        text, proof = args.text.strip(), args.proof_reference.strip()
        if not text or not proof or len(text) > 12000 or len(proof) > 4000:
            raise ValidationError("plan-note requires bounded nonempty text and decision reference")
        row = {"schema_version": 1, "task_id": args.task_id, "plan_sha256": plan["plan_sha256"],
               "text": text, "source": args.source, "proof_reference": proof}
        identity = canonical_sha256(row)
        directory = engine.task_dir(repo, args.task_id)
        path = directory / "plan-notes" / f"{identity}.json"
        if not path.exists():
            row["created_at"] = utc_now()
            row["receipt_sha256"] = canonical_sha256(row)
            engine.atomic_write_json(path, row)
        prior_hash = plan.get("supersedes_plan_sha256")
        previous = read_json(directory / "plan-history" / f"{prior_hash}.json") if prior_hash else None
        engine._write_plan_document(repo, args.task_id, plan, previous=previous)
        return {"status": "RECORDED", "task_status": plan["status"], "task_id": args.task_id, "plan_note": str(path),
                "authority": "UNCHANGED", "next_action": engine.resolve_next_action(repo, args.task_id)}
