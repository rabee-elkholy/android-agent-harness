# Quickstart

## Requirements

- Python 3.10 or newer;
- Git checkout;
- root Gradle Wrapper in the Android/KMP project;
- JDK/Android SDK only when selected build gates need them;
- ADB device only when the adaptive policy selects device verification.

## Clean installation

```bash
python harness_cli.py init --repo /path/to/app --kit .
python harness_cli.py doctor --repo /path/to/app --json --kit .
```

The setup wizard can be rerun before installation. Once v1 is installed, use the lifecycle updater rather than copying files manually.

## Update

```bash
python harness_cli.py update --repo /path/to/app --kit /path/to/new-kit
```

Same-major updates are transactional. If a managed file was changed outside supported tailoring locations, the update stops and preserves the project. A major-version migration requires clean uninstall/install.

## Remove

```bash
python harness_cli.py uninstall --repo /path/to/app --kit .
python harness_cli.py uninstall --repo /path/to/app --kit . --apply
```

The first command is a dry run. The applied command restores original adapters, backs up the current harness, and preserves modified harness material in recovery.

## Daily use

Ask the AI to analyze first. It must present a plan and wait for approval before editing or executing implementation commands. After approval, it follows `.agents/workflows/deliver.md` and the current immutable policy. It does not automatically commit, push, or update Zoho.
