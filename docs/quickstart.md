# Quickstart Guide

Get started with **Android Agent Harness** in 4 simple steps.

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

## Step 3: Run the One-Prompt Installer

Copy the entire content of [`docs/install-prompt.md`](install-prompt.md) and paste it into your chat prompt:

```markdown
Run the Android Harness Kit Installer:
https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/main/docs/install-prompt.md
```

---

## Step 4: Answer the Setup Wizard

The interactive installer will ask you a series of quick questions:
1. **Backup**: Confirm creating a rollback backup.
2. **Product Details**: Your app name and package namespace.
3. **Commit & Device Policies**: Physical device only vs emulator, manual vs automated commits.
4. **AI Tool Adapters**: Select the tools you use (Cursor, Antigravity, Claude, Copilot, etc.).
5. **Zoho Sprints**: Connect Zoho Sprints project management (Optional).

Once completed, the installer will verify:
```
Total test failures: 0
PREFLIGHT PASSED
```

---

## Step 5: (Optional) Verify System Health with Diagnostic Doctor

To perform a comprehensive 12-dimension health audit at any time, paste the diagnostic prompt or run the CLI doctor:

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

You can copy and paste any of the following raw prompt URLs directly into your AI assistant in a new chat:

| Lifecycle Action | Action Summary | Copy-Paste AI Prompt URL |
|---|---|---|
| **Install** | First-time setup, Greenfield bootstrap, or existing app porting | `https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/main/docs/install-prompt.md` |
| **Update** | Upgrade installed harness to latest release with backup | `https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/main/docs/update-prompt.md` |
| **Diagnostic Doctor** | Comprehensive 12-dimension health and safety check | `https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/main/docs/diagnostic-prompt.md` |
| **Rollback** | Restore previous backup state if needed | `https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/main/docs/rollback-prompt.md` |

---

Your Android repository is now governed by the 5-Leaf Review Gate.