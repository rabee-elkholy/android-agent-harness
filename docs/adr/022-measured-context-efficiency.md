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

## Self-contained summary presentation

Default JSON output uses SUMMARY. Identical batch fields are stored once per field
in shared_context; each result retains field-local indexes in shared_context_refs.
Different scoped instructions/contracts remain separate values, never a union.
Warnings, receipt identities and scope, read ranges, expansion flags and outlines
stay visible. Only raw target nodes and advisory neighbor/test lists are shortened,
with counts and same-query --full recovery. Native resolver outputs and persistence
are untouched; the semantic digest is calculated before presentation.

The explicit --full path and mismatched --since return the expanded structure.
Failed/partial batches remain expanded. A summary does not claim that omitted
advisory details were read; matching --since remains caller-controlled and cannot
prove delivery or retention. Mandatory content can exceed host output limits:
there is no hard byte cap that discards safety data.
