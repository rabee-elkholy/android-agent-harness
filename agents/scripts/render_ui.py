"""Generative UI & Visual Artifact Renderer for Android Agent Harness.

Supports high-fidelity interactive Tailwind HTML widgets when running under
Google Antigravity (<agent-embed>), with automatic zero-loss Markdown fallback
for OpenAI Codex, Claude Code, Cursor, and headless CLI environments.
"""
from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
from _environment import (  # noqa: E402
    detect_runtime_profile,
    is_antigravity,
    supports_generative_ui,
)


def _get_artifact_dir() -> Path:
    """Find the active artifact directory for Antigravity or local fallback."""
    # 1. Antigravity artifact directory in environment
    env_art = os.environ.get("ANTIGRAVITY_ARTIFACT_DIR")
    if env_art and Path(env_art).is_dir():
        return Path(env_art).resolve()

    # 2. Look for .gemini/antigravity/brain/<conv_id>
    conv_id = os.environ.get("ANTIGRAVITY_CONVERSATION_ID")
    if conv_id:
        user_home = Path.home()
        brain_path = user_home / ".gemini" / "antigravity" / "brain" / conv_id
        if brain_path.is_dir():
            return brain_path

    # 3. Local repo cache fallback
    repo_cache = SCRIPTS_DIR.parent.parent / ".agents" / "cache"
    if not repo_cache.is_dir():
        repo_cache = SCRIPTS_DIR.parent / "cache"
    repo_cache.mkdir(parents=True, exist_ok=True)
    return repo_cache


def build_review_card_html(
    round_num: int,
    pkg_hash: str,
    leaves: dict[str, dict[str, Any]],
    adjudication: dict[str, Any] | None = None,
    preflight_ok: bool | None = None,
) -> str:
    """Generate self-contained Tailwind HTML widget for the 5-leaf review round."""
    rows_html = []
    for leaf_name, leaf_data in sorted(leaves.items()):
        status = str(leaf_data.get("status") or "UNKNOWN").upper()
        is_pass = "PASS" in status
        badge_bg = "bg-emerald-500/10 text-emerald-600 border-emerald-500/20" if is_pass else "bg-amber-500/10 text-amber-600 border-amber-500/20"
        status_text = "PASS" if is_pass else "FINDINGS"
        findings = leaf_data.get("findings", [])
        
        display_name = leaf_name.replace("-agent", "").replace("-", " ").title()
        
        findings_html = ""
        if findings:
            items = "".join(f"<li class='text-xs text-[var(--foreground)] mt-1 font-mono leading-relaxed bg-[var(--background)]/50 p-2 rounded border border-[var(--border)]/50'>{html.escape(str(f)[:300])}</li>" for f in findings[:5])
            findings_html = f"""
            <details class="mt-2 text-xs text-[var(--muted-foreground)] group">
                <summary class="cursor-pointer hover:text-[var(--foreground)] font-medium select-none flex items-center gap-1">
                    <span class="inline-block transition-transform group-open:rotate-90">▸</span> {len(findings)} Finding(s) Reported
                </summary>
                <ul class="list-none space-y-1.5 mt-2 pl-2 border-l-2 border-[var(--border)]">
                    {items}
                </ul>
            </details>
            """
            
        row = f"""
        <div class="flex flex-col p-3 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:border-[var(--border)]/80 transition-colors">
            <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                    <span class="font-medium text-sm text-[var(--foreground)]">{display_name}</span>
                </div>
                <span class="px-2.5 py-0.5 rounded-full text-xs font-semibold border {badge_bg}">{status_text}</span>
            </div>
            {findings_html}
        </div>
        """
        rows_html.append(row)

    adjudication_html = ""
    if adjudication and adjudication.get("conflicts"):
        conflicts = adjudication.get("conflicts", [])
        conflict_items = "".join(f"<li class='text-xs mt-1'>{html.escape(str(c))}</li>" for c in conflicts)
        adjudication_html = f"""
        <div class="p-3 mt-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-600 text-xs">
            <span class="font-semibold">Reviewer Conflicts Adjudicated:</span>
            <ul class="list-disc list-inside mt-1">{conflict_items}</ul>
        </div>
        """

    preflight_badge = ""
    if preflight_ok is not None:
        pf_bg = "bg-emerald-500/10 text-emerald-600 border-emerald-500/20" if preflight_ok else "bg-amber-500/10 text-amber-600 border-amber-500/20"
        pf_text = "PASSED (0 errors)" if preflight_ok else "PENDING / REQUIRED"
        preflight_badge = f"""
        <div class="flex items-center justify-between text-xs py-2 px-3 mt-3 rounded bg-[var(--background)]/60 border border-[var(--border)]">
            <span class="text-[var(--muted-foreground)]">Preflight Verification Gate:</span>
            <span class="font-semibold px-2 py-0.5 rounded border {pf_bg}">{pf_text}</span>
        </div>
        """

    content = "\n".join(rows_html)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
</head>
<body class="bg-transparent text-[var(--foreground)] antialiased p-3 font-sans">
    <div class="bg-[var(--card)] text-[var(--foreground)] border border-[var(--border)] rounded-xl p-4 shadow-sm max-w-xl mx-auto">
        <div class="flex items-center justify-between border-b border-[var(--border)] pb-3 mb-3">
            <div>
                <h3 class="font-semibold text-base text-[var(--foreground)] flex items-center gap-2">
                    <span>5-Leaf Review Round {round_num}</span>
                </h3>
                <p class="text-xs text-[var(--muted-foreground)] mt-0.5">Package SHA-256: <code class="font-mono">{pkg_hash[:12]}</code></p>
            </div>
            <span class="text-xs font-mono px-2 py-1 rounded bg-[var(--background)] border border-[var(--border)] text-[var(--muted-foreground)]">Round {round_num}/3</span>
        </div>

        <div class="space-y-2.5">
            {content}
        </div>

        {adjudication_html}
        {preflight_badge}
    </div>
</body>
</html>
"""


def build_review_card_markdown(
    round_num: int,
    pkg_hash: str,
    leaves: dict[str, dict[str, Any]],
    adjudication: dict[str, Any] | None = None,
    preflight_ok: bool | None = None,
) -> str:
    """Generate high-signal Markdown summary card for non-GUI environments."""
    lines = [
        f"### Review Round {round_num} Summary",
        f"**Package:** `{pkg_hash[:12]}` | **Round:** {round_num}/3\n",
        "| Reviewer Leaf | Status | Findings / Notes |",
        "| :--- | :---: | :--- |",
    ]
    for leaf_name, leaf_data in sorted(leaves.items()):
        status = str(leaf_data.get("status") or "UNKNOWN").upper()
        is_pass = "PASS" in status
        icon = "[PASS]" if is_pass else "[FINDINGS]"
        findings = leaf_data.get("findings", [])
        display_name = leaf_name.replace("-agent", "").replace("-", " ").title()
        note = f"{len(findings)} finding(s) reported" if findings else "Clean sign-off"
        lines.append(f"| **{display_name}** | {icon} | {note} |")

    if preflight_ok is not None:
        pf_text = "[OK] Passed (0 errors)" if preflight_ok else "[PENDING] Required before assemble"
        lines.append(f"\n**Preflight Gate:** {pf_text}")

    if adjudication and adjudication.get("conflicts"):
        lines.append(f"\n> **Adjudicated Conflicts:** {len(adjudication['conflicts'])} conflict(s) resolved.")

    return "\n".join(lines)


def render_review_summary(
    round_num: int,
    pkg_hash: str,
    leaves: dict[str, dict[str, Any]],
    adjudication: dict[str, Any] | None = None,
    preflight_ok: bool | None = None,
) -> str:
    """Render review summary either as Antigravity <agent-embed> or Markdown."""
    if supports_generative_ui():
        art_dir = _get_artifact_dir()
        file_name = f"review_round_{round_num}_{pkg_hash[:8]}.html"
        html_path = art_dir / file_name
        try:
            html_content = build_review_card_html(
                round_num, pkg_hash, leaves, adjudication, preflight_ok
            )
            html_path.write_text(html_content, encoding="utf-8")
            uri = html_path.resolve().as_uri()
            return f'<agent-embed src="{uri}"></agent-embed>'
        except Exception:
            pass  # Fallback to markdown if write fails

    return build_review_card_markdown(round_num, pkg_hash, leaves, adjudication, preflight_ok)


def main() -> None:
    """CLI tool for testing or manual invocations."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        sample_leaves = {
            "bug-reviewer-agent": {"status": "BUG_PASS", "findings": []},
            "convention-reviewer-agent": {
                "status": "CONVENTION_PASS",
                "findings": ["CleanArchitecture: ViewModel directly exposes MutableStateFlow"],
            },
            "security-reviewer-agent": {"status": "SECURITY_PASS", "findings": []},
            "perf-anr-guardian-agent": {"status": "PERF_PASS", "findings": []},
            "regression-impact-reviewer-agent": {"status": "REGRESSION_PASS", "findings": []},
        }
        res = render_review_summary(1, "a1b2c3d4e5f6", sample_leaves, preflight_ok=True)
        print(res)
    else:
        print("Usage: python render_ui.py --demo")


if __name__ == "__main__":
    main()
