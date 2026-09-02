# Setup Wizard & Configuration Reference

The setup wizard records its answers in `.harness-setup/answers.json` and
writes the applicable product values into `_product.py`. To change answers
after install, re-run the wizard (previous answers are pre-filled) — see
["Changing setup answers after install"](tool-support.md#changing-setup-answers-after-install).

| Parameter | Name | Default | Options / Description |
| :--- | :--- | :--- | :--- |
| `I.0` | **Continue / Backup** | `Backup` | Continue the install and create the rollback backup. |
| `I.1` | **Product Name** | *Auto-detected* | Clean product display name. |
| `I.2` | **Python Executable** | *Auto-detected* | Asked only when Python is missing or ambiguous. |
| `I.3` | **Git Commit Policy** | `Manual in IDE` | Developer commits manually *(Recommended)* or agent commits only on explicit request. |
| `I.4` | **Device Target Policy** | `Physical + Emulator` | Both allowed *(Recommended)* or physical phone only. |
| `I.5` | **Application Module** | *Auto-detected* | Asked only when the module is missing or ambiguous. |
| `I.6` | **Launcher / APK** | *Auto-detected* | Asked only when the launcher or APK is missing or ambiguous. |
| `I.10` | **Install Confirmation** | `Ask first` | Require confirmation before device installation. |
| `I.14` | **AI Tool Adapters** | *Multi-select* | Select only the IDEs and agents used for this project. |
| `I.15` | **Unit Tests Gate** | `Yes` | Run the targeted unit-test task before assemble. |
| `I.16` | **Zoho Sprints MCP** | *Optional* | Configure the built-in integration without copying tokens. |
| `I.18` | **Tracker Language** | `English titles + Arabic notes` | Language policy for task tracker content (Zoho / Jira / Linear / GitHub). |
| `I.19` | **Daily Flavor** | *Conditional* | Asked only when Gradle product flavors are discovered. |
| `I.20` | **Project Tracker** | `Zoho Sprints` | Zoho, GitHub Projects, Jira, Linear, or none. Writes `PM_PROVIDER`. |
| `I.21` | **Pre-Commit Git Gate** | `Yes` | Install the staged quality gate; use `--no-git-gate` only when managing your own hook. |
| `I.22` | **Device Verification** | `Manual Smoke` | Interactive manual verification on device *(Recommended)* or disabled. |
| `b_*` | **Greenfield Architecture** | *Conditional* | Platform, architecture, DI, navigation, UI, database, networking, and locale questions for blank projects. |

The full interview protocol the installing agent executes lives in
[`setup-prompt.md`](setup-prompt.md).
