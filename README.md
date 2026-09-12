# Android Agent Harness

A local, zero-dependency development harness for Android projects. It is designed to improve AI-assisted implementation quality while keeping model calls, build work, and developer interruption proportional to the actual change.

## v1 guarantees

- Analysis and planning are read-only. No implementation starts until the developer explicitly approves the exact plan.
- A deterministic classifier selects only relevant skills, tests, reviewers, build steps, and device checks.
- Every gate is bound to one repository, approved plan, complete delivery snapshot, change set, run id, harness version, and producer.
- Evidence is append-only. The final verifier is read-only and rejects stale, incomplete, forged, or cross-run evidence.
- APK output is an artifact set, so split APKs are built, hashed, installed, and launched as one identity.
- Clean install, same-major update, dry-run uninstall, backup, rollback, and user-file ownership are explicit lifecycle operations.
- Zoho Sprints keeps the existing workflow and never changes without `update zoho`, an approved plan that lists `--external-write zoho_sprints`, and a stable operation id.
- Hosts report their real enforcement level. Executable hooks can hard-enforce covered mutations; conversational approval remains `RULE_ENFORCED` unless a future host supplies non-forgeable proof.

## Install

### Chat installation (recommended)

Open the Android project root in your coding agent, then paste:

```text
Read https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.0.13/docs/install-or-update-prompt.md and follow all instructions.
```

The AI agent will:
1. Perform read-only discovery of your Android project structure.
2. Ask setup questions directly in chat with recommended choices marked with **(Recommended)**.
3. Present a precise installation plan with an executable non-interference snapshot guarantee.
4. Wait for your explicit approval before modifying anything or provisioning the kit.
5. Provision the pinned kit into `~/.android-harness/kit`, verify integrity, and perform an atomic clean install or update.
6. Run `doctor` verification and verify zero application files were altered.

### Terminal installation (alternative)

Use a clean Android Git checkout with its Gradle Wrapper and a kit checkout
pinned to the same immutable release tag:

```bash
git clone --depth 1 --branch v1.0.13 --single-branch https://github.com/rabee-elkholy/android-agent-harness.git /path/to/android-agent-harness
python /path/to/android-agent-harness/harness_cli.py init --repo /path/to/android-project --kit /path/to/android-agent-harness
```

The wizard writes local answers, then the lifecycle engine stages and validates `.agents`, creates only selected host adapters, records ownership, and keeps all harness files out of the shared Git index through `.git/info/exclude`.

Legacy pre-v1 installs are replaced atomically in one process so active coding-agent hooks are not broken:

```bash
python harness_cli.py init --replace-legacy --repo /path/to/android-project --kit .
```

## Task lifecycle

```bash
python .agents/scripts/workflow.py draft --repo . --task-id TASK-1 --outcome "Describe the result" --expected-surfaces BUSINESS_LOGIC --expected-modules :app
# Present plan and wait for explicit approval.
python .agents/scripts/workflow.py approve --repo . --task-id TASK-1 --source conversation --proof-reference MESSAGE-ID --enforcement-tier RULE_ENFORCED
python .agents/scripts/workflow.py begin --repo . --task-id TASK-1
# Implement the approved scope.
python .agents/scripts/workflow.py prepare-verification --repo . --task-id TASK-1
```

The developer—not the AI agent—approves the plan. For a sensitive
final snapshot, the developer separately approves it (solicited interactively
in chat via `ask_question`, or executed directly from their terminal):

```bash
# In chat: the agent prompts via ask_question and records with --source conversation
python .agents/scripts/workflow.py approve-sensitive --repo . --task-id TASK-1 --source conversation --proof-reference DEVELOPER-CONFIRMATION --enforcement-tier RULE_ENFORCED

# In terminal: the developer may also run directly
python .agents/scripts/workflow.py approve-sensitive --repo . --task-id TASK-1 --source developer_terminal --proof-reference LOCAL-CONFIRMATION --enforcement-tier RULE_ENFORCED
```

Read `current-run.json` and execute only the selected gates. If reviews are required, run `review_package.py`, dispatch exactly the selected reviewers, then ingest their unchanged responses or structured reports with `record_review.py`.

Finish with:

```bash
python .agents/scripts/workflow.py verify --repo . --task-id TASK-1
python .agents/scripts/workflow.py complete --repo . --task-id TASK-1
```

## Lifecycle

```bash
python harness_cli.py update --repo /path/to/android-project --kit /path/to/new-kit
python harness_cli.py uninstall --repo /path/to/android-project          # dry run
python harness_cli.py uninstall --repo /path/to/android-project --apply
python harness_cli.py doctor --repo /path/to/android-project --json
python harness_cli.py selftest --kit .
```

Updates are allowed only within architecture major 1, refuse modified managed files, preserve project-tailored Android references and Zoho defaults, validate the staged engine, and roll back on failure. Uninstall restores pre-install files and places modified harness-owned material in `.harness-recovery`.

See [architecture](docs/architecture.md), [workflows](docs/workflows.md), and [quickstart](docs/quickstart.md).
