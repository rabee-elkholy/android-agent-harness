---
description: Scaffold an MVI Compose feature, then implement and run the 5-leaf gate.
---

# Scaffold New MVI Feature in Rashaqa

Follow `.agents/rules/harness-rules.md`. Do not commit.

## Steps

1. If name/scope/API is missing, `ask_question` in the developer's language.
2. `python .agents/scripts/new_feature_scaffold.py <featureName>`
   Creates `Contract` (`State`/`Action`/`Event`), `ViewModel`, `ui/Screen`, `Fragment`, and string keys. This is a skeleton — wire UseCase + navigation before review.
3. Implement real behavior. UI guidance: `android-ui-expert-agent`.
4. `check_strings.py`, then the 5-leaf review, tests, assemble.
