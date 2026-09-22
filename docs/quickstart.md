# Quickstart

## Requirements

- Python 3.10 or newer;
- Git checkout;
- root Gradle Wrapper in the Android/KMP project;
- JDK/Android SDK only when selected build gates need them;
- ADB device only when the adaptive policy selects device verification.

## Chat installation (recommended)

Open the Android project root in your coding agent and paste:

```text
Read https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.0.60/docs/install-or-update-prompt.md and follow all instructions.
```

The agent interviews you in chat, preserves references, shows an explicit plan, provisions the pinned kit into `~/.android-harness/kit` (or `%USERPROFILE%\.android-harness\kit` on Windows), and runs doctor.

## Terminal installation (alternative)

POSIX:
```bash
python ~/.android-harness/kit/harness_cli.py init --repo /path/to/app --kit ~/.android-harness/kit
python ~/.android-harness/kit/harness_cli.py doctor --repo /path/to/app --kit ~/.android-harness/kit --json
```

Windows:
```powershell
python "%USERPROFILE%\.android-harness\kit\harness_cli.py" init --repo C:\path\to\app --kit "%USERPROFILE%\.android-harness\kit"
python "%USERPROFILE%\.android-harness\kit\harness_cli.py" doctor --repo C:\path\to\app --kit "%USERPROFILE%\.android-harness\kit" --json
```

The setup wizard can be rerun before installation. Once v1 is installed, use the lifecycle updater rather than copying files manually.

## Update

POSIX:
```bash
python ~/.android-harness/kit/harness_cli.py update --repo /path/to/app --kit /path/to/new-kit
```

Windows:
```powershell
python "%USERPROFILE%\.android-harness\kit\harness_cli.py" update --repo C:\path\to\app --kit C:\path\to\new-kit
```

Same-major updates are transactional. If a managed file was changed outside supported tailoring locations, the update stops and preserves the project. A major-version migration requires clean uninstall/install.

## Remove

POSIX:
```bash
python ~/.android-harness/kit/harness_cli.py uninstall --repo /path/to/app --kit ~/.android-harness/kit
python ~/.android-harness/kit/harness_cli.py uninstall --repo /path/to/app --kit ~/.android-harness/kit --apply
```

Windows:
```powershell
python "%USERPROFILE%\.android-harness\kit\harness_cli.py" uninstall --repo C:\path\to\app --kit "%USERPROFILE%\.android-harness\kit"
python "%USERPROFILE%\.android-harness\kit\harness_cli.py" uninstall --repo C:\path\to\app --kit "%USERPROFILE%\.android-harness\kit" --apply
```

The first command is a dry run. The applied command restores original adapters, backs up the current harness, and preserves modified harness material in recovery.

## Daily use

Ask the AI to analyze first. It must present a plan and wait for approval before editing or executing implementation commands. After approval, it follows `.agents/workflows/deliver.md` and the current immutable policy. It operates the harness via documented public command contracts without eagerly inspecting internal engine scripts. It does not automatically commit, push, or update Zoho. When the lifecycle state is unclear, `python ~/.android-harness/kit/harness_cli.py task status --repo /path/to/app --next` prints the safest next command without executing it.
