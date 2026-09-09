# Porting and project tailoring

Do not copy another application's installed `.agents` directory. Run the v1
installer against the target checkout so discovery creates a fresh product
configuration and ownership manifest.

## Project values

| Value | Source |
|---|---|
| Product and project kind | Gradle settings and Android plugins |
| Application ID and launcher | Android module configuration and manifest |
| Assemble/test tasks | Selected module and exact build variant |
| APK set | Gradle output metadata after assemble |
| UI, DI, persistence, structure | Existing build/source inspection |
| Locales | Actual `res/values*` directories |
| Device policy | Developer setup answer |
| Enforcement tier | Detected host capability, never a setup claim |

For multiple flavor dimensions or custom build types, enter the exact combined
variant (for example `FreeEuStaging`). Library-only projects keep launcher/APK
empty and never select device gates.

## Tailoring boundary

Project conventions may be added to the documented Android reference files and
Zoho workflow defaults. Compatible update preserves those locations. Tailoring
must not weaken the kernel, approval requirement, deterministic policy,
evidence binding, Git/device safety, or terminal tracker-state ownership.

## Verification after installation

```bash
python .agents/scripts/harness_doctor.py --json
python .agents/scripts/_vnext_selftest.py
python .agents/scripts/_hook_selftest.py
```

The install itself does not run the Android build or modify application/Gradle
source. Run project gates only inside an approved task.

## Secrets and host configuration

Never copy `local.properties`, SDK paths, keystores, provider JSON, tokens, or
user-level IDE configuration between projects. Zoho credentials remain under
the user's profile; project MCP files contain command/config paths only.
