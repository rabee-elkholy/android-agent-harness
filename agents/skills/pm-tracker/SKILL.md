---
name: pm-tracker
description: Safe Universal PM MCP and Zoho Sprints synchronization (`pm discover`, `pm authorize`, `pm prepare-report`, `zoho start-sync`, `zoho delivery-sync`). Use before reading or updating external tickets.
version: 1.0.0
kernel-major: 1
---

# PM Tracker Integration Skill

Follow `.agents/rules/pm-and-context-bridge.md` and `.agents/workflows/pm-tracker.md`. Always preview target ticket mutations, record explicit developer authorization (`pm authorize` or `zoho authorize`), preserve original Bug descriptions, and never transition items to `Done`/`Closed` without explicit developer instruction.
