# ADR-022: Explicit context presentation and operation-local reuse

Status: implemented in the current maintenance tree.

Extend existing native context, metrics and verification mechanisms. Default context
is self-contained. A caller-provided matching semantic digest permits presentation
compaction only after current discovery; no global marker claims prior conversation
knowledge. Native result dictionaries remain complete and approvals are unchanged.

A batch shares facts, notes and instruction reads only inside its bracketed source
check. Review topology indexes native graph paths once per invocation. No persistent
cache of evidence, permission or PASS is introduced. Before/after freshness checks
and review independence remain authoritative.

Architecture context uses already resolved graph/facts/contract inputs. It is bounded
to 8 KiB, reports uncertainty and is never authorization. Review packages include a
package-local graph summary without implementer reasoning or other reviewer findings.

Existing opt-in metrics accept legacy v1 and bounded v2 numeric substeps. Nested
work is excluded from command elapsed totals. Tokens and cost remain unavailable.
Default-off and write failure preserve command behavior. Command ownership is
captured before a command changes focus. No host hook schema, model policy, device
behavior or task/router state changes.
