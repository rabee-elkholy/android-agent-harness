# Recipe: add a tool adapter

1. Add a minimal template under `agents/tool-adapters/` that points to the
   canonical kernel. Do not duplicate review/gate policy in the adapter.
2. Register only exact generated paths in `install_tool_adapters.py` and
   `lifecycle.py`; never claim an entire user configuration directory.
3. Add the tool ID and label to the setup wizard.
4. If a native hook exists, translate its payload to `pre_tool_safety.py`,
   bound execution time, and report its actual interception capability.
5. Test install, update, rollback, uninstall restoration, unrelated config
   preservation, malformed hook input, and allow/deny parity.

The adapter must never copy tokens, SDK paths, or user-level configuration and
must never advertise prompt-only behavior as hard enforcement.
