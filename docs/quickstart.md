# Quickstart Guide

> **Deterministic Android Engineering for the AI Era**  
> *Turn Any AI Assistant into an Uncompromising Senior Android Engineering Team.*

---

## Step 1: Open Your Android Project Root
Launch your preferred AI-enabled IDE or assistant (e.g. Google Antigravity, Cursor, Claude Code, Windsurf) and ensure your workspace is set to your **Android project root directory**.

---

## Step 2: Choose a Reasoning Model
For initial setup and structural porting, select a model capable of deep architectural reasoning:
- **Google Antigravity**: `Gemini 3.1 Pro (Deep Think)` or `Gemini 3.7 Flash`
- **Cursor**: `Claude Opus 5`, `GPT-5.6 Sol`, or `Claude 3.7 Sonnet (Thinking)`
- **Claude Code**: `Claude Opus 5 (Adaptive Thinking)` or `Claude 3.7 Sonnet (Thinking)`
- **GitHub Copilot**: `Claude 3.7 Sonnet (Thinking)` or `GPT-5.6 Sol`
- **OpenAI Codex**: `GPT-5.6 Sol` or `OpenAI o3`
- **Windsurf / Cline / Continue**: `Claude 3.7 Sonnet (Thinking)` or `DeepSeek-R1`

---

## Step 3: Run the Installer (AI Prompt or CLI)

### Option A: One-Prompt Installer & Updater (Chat Prompt — Recommended)

Copy the entire content of [`docs/install-or-update-prompt.md`](install-or-update-prompt.md) or paste the URL into your chat prompt:

```markdown
Run the Android Agent Harness Installer or Updater:
https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v0.25.8/docs/install-or-update-prompt.md
```

### Option B: Standalone CLI (Terminal)

```bash
pipx install git+https://github.com/rabee-elkholy/android-agent-harness.git
android-harness init
```

---

## Step 4: Answer the Setup Wizard

The interactive installer will ask you a series of quick questions:
1. **Backup**: Confirm creating a rollback backup.
2. **Product Details**: Your app name and discovered project facts.
3. **Commit & Device Policies**: Physical device only vs emulator, manual vs automated commits.
4. **AI Tool Adapters**: Select the tools you use (Cursor, Antigravity, Claude, Copilot, etc.).
5. **Quality & Project Policy**: Unit tests, Zoho/other tracker, language, flavor, and the default-on pre-commit git gate.

Once completed, the installer will automatically run the 12-dimension diagnostic doctor (`harness_doctor.py`), verify `.gitignore` security, and confirm:
```
Total test failures: 0
PREFLIGHT PASSED
[SUCCESS] Harness checks passed and the configured delivery gates are ready.
```

---

## Step 5: (Optional) Verify System Health with Diagnostic Doctor

To perform a comprehensive 12-dimension health audit at any time, audit `.gitignore` security rules, or check working tree status, paste the diagnostic prompt or run the CLI doctor:

```markdown
Run the Android Agent Harness Diagnostic Doctor:
https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v0.25.8/docs/diagnostic-prompt.md
```

Or execute directly from your terminal:
```bash
python .agents/scripts/harness_doctor.py
```

---

## One-Click Lifecycle Prompts Library

You can copy and paste any of the following prompts directly into your AI assistant in a new chat:

### 1. Install & Update Prompt (Setup, Greenfield Bootstrap & In-Place Upgrades)
- **What it does**: Sets up or upgrades `.agents/`, safety hooks, IDE adapters, and architectural rules tailored to your project.
- **Why it matters**: Turns standard AI coding assistants into architecture-compliant engineering teammates and delivers new lint rules and security hardening.
- **When to use**: Onboarding an existing Android repository, bootstrapping a brand-new Greenfield app, or upgrading to a new harness release.
- **Prompt URL**:
```markdown
Read and execute the Android Agent Harness installer or updater:
https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v0.25.8/docs/install-or-update-prompt.md
```

### 3. Diagnostic Doctor Prompt (12-Dimension Health Check)
- **What it does**: Audits 12 core dimensions of your repository (environment, subagents, product config, templates, hooks, preflight, ADB).
- **Why it matters**: Confirms 100% operational health and active safety enforcement.
- **When to use**: After installing, updating, switching IDEs, or troubleshooting warnings.
- **Prompt URL**:
```markdown
Read and execute the Android Agent Harness diagnostic doctor:
https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v0.25.8/docs/diagnostic-prompt.md
```

### 4. Rollback Prompt (Instant Backup Restoration)
- **What it does**: Restores your previous `.agents/` configuration and IDE adapters from the `.harness-backup/` snapshot.
- **Why it matters**: Provides a zero-risk rollback guarantee if an update does not suit your project.
- **When to use**: To revert recent harness configuration updates.
- **Prompt URL**:
```markdown
Read and execute the Android Agent Harness rollback:
https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v0.25.8/docs/rollback-prompt.md
```

---

## Standalone CLI Reference

Install globally via `pipx` directly from this repository (PyPI publication pending):

```bash
pipx install git+https://github.com/rabee-elkholy/android-agent-harness.git
```

No install needed? Run it in place from any kit clone:

```bash
python harness_cli.py --help
```

| Command | Purpose |
| :--- | :--- |
| `android-harness init [--repo PATH] [--lang en\|ar]` | Run the setup wizard against an Android checkout; provisions the kit pinned to an exact release tag. |
| `android-harness update [--repo PATH] [--force]` | Refresh the local kit engine to the latest release tag and print upgrade steps. |
| `android-harness explain [--last N] [--repo PATH]` | Print recent safety-hook decisions from the append-only audit log of the checkout whose hooks ran. |
| `android-harness verify [--repo PATH] [--verdict PATH] [--rerun-checks]` | Validate a review `verdict.json` artifact against actual repo state (package hash, per-file hashes, evidenced leaves). Exit codes: 0 PASS, 1 FAIL, 2 STALE/incomplete. |
| `android-harness doctor [--repo PATH] [--json] [--device]` | Audit 12-dimension health at any time. |
| `android-harness preflight [--repo PATH]` | Rapid preflight checks (strings + Room + fast lint) against the target checkout (prefers the checkout's own `.agents` engine). |
| `android-harness selftest` | Run the kit hook selftest suite in the kit checkout. |
| `android-harness version` | Print the active kit engine version. |

---

## Installation & Setup Modes

### Mode A: Existing Android / KMP App
Run the installer in an established codebase. The setup wizard inspects your `libs.versions.toml`, Gradle dependencies, and existing architecture (MVI/MVVM, Compose, Room, Koin/Hilt) and generates custom domain reference skills tailored to your app.

### Mode B: Greenfield / Blank Project
For brand-new or blank projects, the wizard guides you through an **8-question Architecture Foundation Questionnaire**:
1. **Target Platform**: Android Native vs Kotlin Multiplatform (KMP).
2. **Architecture**: MVI (Unidirectional) vs MVVM.
3. **Dependency Injection**: Koin vs Hilt vs Manual.
4. **Navigation**: Voyager vs AndroidX Navigation Compose.
5. **UI Framework**: Jetpack Compose vs XML Views.
6. **Local Database**: Room vs SQLDelight vs DataStore (or none).
7. **Networking**: Ktor Client vs Retrofit + OkHttp.
8. **Localization**: Bilingual Arabic (RTL) + English (LTR) vs Single Locale.

Every wizard question and default is documented in the [Setup Wizard Reference](setup-wizard.md).

---

Your Android repository is now governed by the 5-Leaf Review Gate.
