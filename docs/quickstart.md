# Quickstart Guide

Get started with **Android Agent Harness** in 5 simple steps.

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

## Step 3: Run the Installer (CLI or AI Prompt)

### Option A: Standalone CLI (Terminal)

```bash
pipx install git+https://github.com/rabee-elkholy/android-harness-kit.git
android-harness init
```

### Option B: One-Prompt Installer (Chat Prompt)

Copy the entire content of [`docs/install-prompt.md`](install-prompt.md) and paste it into your chat prompt:

```markdown
Run the Android Harness Kit Installer:
https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/main/docs/install-prompt.md
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
Run the Android Harness Kit Diagnostic Doctor:
https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/main/docs/diagnostic-prompt.md
```

Or execute directly from your terminal:
```bash
python .agents/scripts/harness_doctor.py
```

---

## One-Click Lifecycle Prompts Library

You can copy and paste any of the following prompts directly into your AI assistant in a new chat:

### 1. Install Prompt (Setup & Greenfield Bootstrap)
- **What it does**: Sets up `.agents/`, safety hooks, IDE adapters, and architectural rules tailored to your project.
- **Why it matters**: Turns standard AI coding assistants into architecture-compliant engineering teammates.
- **When to use**: Onboarding an existing Android repository or bootstrapping a brand-new Greenfield app.
- **Prompt URL**:
```markdown
Read and execute the Android Harness Kit installer:
https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/main/docs/install-prompt.md
```

### 2. Update Prompt (Harness Upgrade)
- **What it does**: Upgrades `.agents/` scripts, hooks, and subagent prompts to the newest release while retaining your custom app settings.
- **Why it matters**: Delivers new lint rules, security hardening, and framework improvements without touching your application source code.
- **When to use**: Whenever a new harness release is published.
- **Prompt URL**:
```markdown
Read and execute the Android Harness Kit updater:
https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/main/docs/update-prompt.md
```

### 3. Diagnostic Doctor Prompt (12-Dimension Health Check)
- **What it does**: Audits 12 core dimensions of your repository (environment, subagents, product config, templates, hooks, preflight, ADB).
- **Why it matters**: Confirms 100% operational health and active safety enforcement.
- **When to use**: After installing, updating, switching IDEs, or troubleshooting warnings.
- **Prompt URL**:
```markdown
Read and execute the Android Harness Kit diagnostic doctor:
https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/main/docs/diagnostic-prompt.md
```

### 4. Rollback Prompt (Instant Backup Restoration)
- **What it does**: Restores your previous `.agents/` configuration and IDE adapters from the `.harness-backup/` snapshot.
- **Why it matters**: Provides a zero-risk rollback guarantee if an update does not suit your project.
- **When to use**: To revert recent harness configuration updates.
- **Prompt URL**:
```markdown
Read and execute the Android Harness Kit rollback:
https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/main/docs/rollback-prompt.md
```

---

Your Android repository is now governed by the 5-Leaf Review Gate.
