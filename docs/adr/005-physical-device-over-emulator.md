# ADR-005: Physical device over emulator

## Context

Emulator-only testing masked real-device failures: sensor lifecycle bugs, ANR
profiles that only appear on hardware, RTL rendering differences, and
stale-emulator confusion during automated runs.

## Decision

`adb monkey` and emulator/AVD tooling are denied by default; every
device-bound adb verb (including privilege/data verbs such as `root`,
`remount`, `backup`, `reboot`, `sync`) requires an explicit `-d`/
`-s <serial>` binding; `run_device.py`, `logcat_doctor.py`, and
`capture_screen.py` consume `_product.py ALLOW_EMULATOR` (setup I.4): the
default allows both physical devices and emulators, while "physical-only"
locks out `emulator-` serials entirely.

## Consequences

Real-hardware evidence is the norm and device policy is centralized in one
configuration point consumed by all runners. Cost: teams running
physical-only need a connected device or delivery stalls, and emulator-based
CI scenarios require explicitly opting in via setup I.4.
