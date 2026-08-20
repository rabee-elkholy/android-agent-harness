---
description: Fail if English/Arabic string keys drift or user-facing text is hardcoded.
---

# Check Localization & Strings Parity

Follow `.agents/rules/harness-rules.md`.

## Steps

1. `python .agents/scripts/check_strings.py`
2. Exit code 1 is a gate failure. Add missing keys to both `values/strings.xml` and `values-ar/strings.xml`. Extract hardcoded text. Do not leave English in the Arabic file for user-facing copy.
