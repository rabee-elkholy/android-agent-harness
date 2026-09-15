# Daily work notes
 
Follow `.agents/rules/harness-rules.md`. Consult [Public Command Contract](./command-contract.md) to operate the harness.

## Harness Execution Boundary
Installed harness engine source under `.agents/scripts/**` is an implementation detail. Do not inspect or recursively read harness Python scripts before executing documented commands. Follow [Public Command Contract](./command-contract.md) and execute documented commands directly.

## Checkout facts
- Product configuration & variant artifacts: Generated into `.agents/scripts/_product.py` (read by harness commands automatically; see [Public Command Contract](./command-contract.md))
- Derived architecture facts & component contracts: `.agents/project-context/project-facts.json`
- Human architectural conventions & notes: `.agents/project-context/project-notes.md`
- Source roots: classic `app/src/main` or KMP `androidMain` — use what exists on disk
- Locales: the `values` / `values-*` folders that exist

## Where to read the rest
- Project Architecture: `.agents/project-context/architecture.md` (then `architecture-guidelines.md`)
- UI / Layout / Theming: `.agents/project-context/ui.md` (then `ui-layout-and-theming.md`)
- Database / Persistence: `.agents/project-context/persistence.md` (then `database-and-persistence.md`)
- Technical Capabilities & Conventions: `.agents/project-context/conventions.md`
- Performance / Optimization: `performance-and-optimization.md`
- Test Quality: `test-quality-guidelines.md`
- Automated Skills: `automated-skills.md`
- Specialized domain overrides: `.agents/project-context/legacy-overrides/` (if present)
