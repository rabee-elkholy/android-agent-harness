# Sync kit ↔ parent product

The kit was extracted from a production Android harness (the parent app). **Do not copy either `.agents` folder onto the other.** That is the fastest way to destroy product identity on one side and portability on the other.

Use a **file-level patch**, one direction, then prove it.

## What belongs where

| Kind | Examples | Kit | Parent product |
|---|---|---|---|
| **Engine** | `pre_tool_safety.py`, `_live_process.py`, `run_gradle_task.py`, `run_device.py`, `_hook_selftest.py`, `hooks.json`, 5 reviewer JSON files, `*_PASS` protocol | Yes | Yes |
| **Example leftovers** | Rashaqa / `Fitness_Android` / `com.madarsoft` / `:app:assembleDebug` / `SplashActivity` / ads-streak-GPS skill refs | **Must stay** (setup ports them away) | **Must stay** (this is the real app) |
| **Kit packaging** | `docs/install-prompt.md`, `update-prompt.md`, `setup-prompt.md`, `install_tool_adapters.py --tools`, empty `mcp_config.json` | Yes | No (do not “install” the kit into the parent as if it were a stranger app) |
| **Machine / secrets** | `state/`, `local.properties`, `~/.gemini`, tokens, MCP servers, `sdk.dir` | Never | Never copy into the kit |

Do not weaken the engine (see `docs/porting.md`).

## Never

- Overwrite the parent’s live `.agents` with the kit tree (or with `dist/android-harness-kit`).
- Overwrite the GitHub kit with the parent’s live `.agents` (it contains `state/`, product-only edits, and often a nested `dist/`).
- Run `install-prompt.md` or `update-prompt.md` **on the parent product**. Those prompts port *away* from the example identity. The parent *is* that identity.
- Copy `~/.gemini` either way.
- Naive find-replace of the product name in either direction.

## Parent → kit (promote an engine fix)

1. Backup the kit clone.
2. Diff **only** the engine files you changed in the parent (scripts, hooks, reviewer JSON, selftest). Skip `state/`, MCP, Gemini, `dist/`.
3. Copy those files into `android-harness-kit/agents/…` (same relative path).
4. If the change is product-specific (package, launcher, theme, ads/GPS copy), **do not** promote it unless it should become the new **example leftover** for setup to port.
5. In the kit: `$PY agents/scripts/_hook_selftest.py` from a throwaway copy is not enough — run the kit’s selftest the way this repo expects, or copy the file then run selftest inside a **non-parent** install. Kit tree still **must** contain the leftover tokens listed in `docs/porting.md`.
6. Commit the kit. Products update with `docs/update-prompt.md` (not the parent).

## Kit → parent (bring a portable engine fix home)

1. Backup the parent’s live `.agents` (not only `dist/`).
2. Diff the same engine files in the kit vs the parent.
3. Copy **only** those engine files into the parent’s live `.agents/scripts` (etc.).
4. Do **not** replace parent `harness-rules.md` with a genericized kit copy. Do **not** replace parent skill refs with stubs. Do **not** run leftover-grep-as-if-foreign-app (the parent should still say Rashaqa / `:app` / its real launcher).
5. Keep parent I.4 (physical-only) and git policy as they are unless you intend to change them.
6. `python .agents/scripts/_hook_selftest.py` in the parent → `Total test failures: 0`. Then a **new chat**.

## If you are unsure which bucket a file is

Treat it as **parent-only** until you can name the engine behavior it changes (barrier, heartbeat, five leaves, monkey deny). Packaging docs never go to the parent. Product skills never go to the kit unless they are the example leftovers setup already ships.
