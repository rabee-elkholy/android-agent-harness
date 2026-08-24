"""One-shot generator for agents/command-packs/*.md.template (dev utility)."""
from pathlib import Path

d = Path(__file__).resolve().parent.parent / "agents" / "command-packs"
d.mkdir(parents=True, exist_ok=True)
FM = '---\ndescription: {desc}\nargument-hint: "{hint}"\n---\n\n'
HEAD = "Read `.agents/rules/harness-rules.md` first. That file wins over everything in this session.\n\n"
TAIL = "\nUser request / context: $ARGUMENTS\n"

packs = {
    "deliver": ("Deliver an Android change end-to-end: plan artifact, implement, 5-leaf review gate, preflight, assemble, device phases.", "[what to deliver]"),
    "debug": ("Hypothesis-driven Android debugging with forensics, 5-leaf review, and physical-device validation.", "[bug symptoms / Zoho id]"),
    "new-feature": ("Implement a new Android feature through the mandatory planning artifact and 5-leaf delivery gate.", "[feature description]"),
    "preflight": ("Run the preflight sanity suite: hook selftest, string parity, Room migration gate, fast Kotlin lint.", ""),
    "check-strings": ("Fail on English/Arabic string key drift or hardcoded user-facing text; fix both locale files.", ""),
    "perf-audit": ("Static + optional device ANR audit via perf_guard and perf-anr-guardian-agent.", "[optional file paths]"),
    "test-quality-audit": ("Audit modified unit/UI test files for assertion depth, dispatchers, and mocking integrity.", ""),
    "crash-triage": ("Pull physical-device fatals via logcat_doctor and hand them to qa-diagnostics-agent.", "[symptoms]"),
    "commit-msg": ("Draft a Conventional Commit message for Android Studio after every phase is Pass. The agent never commits.", ""),
    "zoho-sprints": ("Zoho Sprints ingest/create/update playbook. Mutate only on explicit update zoho.", "[item id or update zoho]"),
}

for name, (desc, hint) in packs.items():
    body = HEAD + f"Execute the playbook `.agents/workflows/{name}.md` exactly, step by step. Do not skip or reorder gates.\n"
    (d / f"{name}.md.template").write_text(FM.format(desc=desc, hint=hint) + body + TAIL, encoding="utf-8")

doctor = '---\ndescription: 12-dimension harness health diagnostic with actionable remediation.\n---\n\n'
doctor += HEAD
doctor += (
    "Run the full diagnostic engine from the repository root:\n\n"
    "```bash\n{{PY}} .agents/scripts/harness_doctor.py --device\n```\n\n"
    "Present the 12-dimension summary as a compact markdown table "
    "(Dimension | Status | Detail). For every [WARN] or [FAIL]: root cause, then the exact "
    "copy-paste terminal command to fix it, then re-run the doctor to confirm recovery. "
    "If everything passes, declare the harness ready for delivery.\n"
)
(d / "doctor.md.template").write_text(doctor, encoding="utf-8")
print("written:", len(list(d.glob("*.template"))))
